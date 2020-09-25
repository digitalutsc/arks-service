<?php

namespace Noid\Lib\Custom;
require_once "NoidLib/custom/NoidArk.php";

use Noid\Lib\Db;
use Noid\Lib\Globals;
use Noid\Lib\Helper;
use Noid\Lib\Log;
use Noid\Lib\Custom\NoidArk;
use Noid\Lib\Storage\DatabaseInterface;

class Database extends Db{

    /**
     * @param $dbdir
     * @param $contact
     * @param null $template
     * @param string $term
     * @param string $naan Name Assigning Authority Number
     * @param string $naa
     * @param string $subnaa
     * @return string|null
     */
    static public function dbcreate($dbdir, $contact, $template = NULL, $term = '-', $naan = '', $naa = '', $subnaa = '') {
        NoidArk::init();

        $total = NULL;
        $noid = NULL;

        $prefix = NULL;
        $mask = NULL;
        $gen_type = NULL;
        $msg = NULL;
        $genonly = NULL;
        if(is_null($template)){
            $genonly = 0;
            $template = '.zd';
        }
        else{
            $genonly = 1;           # not generated ids only
        }

        $total = Helper::parseTemplate($template, $prefix, $mask, $gen_type, $msg);
        if(!$total){
            Log::addmsg($noid, $msg);
            return NULL;
        }
        $synonym = 'noid' . ($genonly ? '_' . $msg : 'any');

        # Type check various parameters.
        #
        if(empty($contact) || trim($contact) == ''){
            Log::addmsg($noid, sprintf('error: contact (%s) must be non-empty.', $contact));
            return NULL;
        }

        $term = $term ? : '-';
        if(!in_array($term, array('long', 'medium', 'short', '-'))){
            Log::addmsg($noid, sprintf('error: term (%s) must be either "long", "medium", "-", or "short".', $term));
            return NULL;
        }

        $naa = (string)$naa;
        $naan = (string)$naan;
        $subnaa = (string)$subnaa;

        if($term === 'long'
            && (!strlen(trim($naan)) || !strlen(trim($naa)) || !strlen(trim($subnaa)))
        ){
            Log::addmsg($noid, sprintf('error: longterm identifiers require an NAA Number, NAA, and SubNAA.'));
            return NULL;
        }
        # xxx should be able to check naa and naan live against registry
        # yyy code should invite to apply for NAAN by email to ark@cdlib.org
        # yyy ARK only? why not DOI/handle?
        if($term === 'long' && !preg_match('/\d\d\d\d\d/', $naan)){
            Log::addmsg($noid, sprintf('error: term of "long" requires a 5-digit NAAN (00000 if none), and non-empty string values for NAA and SubNAA.'));
            return NULL;
        }

        $noid = self::dbopen($dbdir, DatabaseInterface::DB_CREATE);
        if(!$noid){
            Log::addmsg(NULL, "error: a NOID database can not be created in: " . $dbdir . "." . PHP_EOL
                . "\t" . 'To permit creation of a new minter, rename' . PHP_EOL
                . "\t" . 'or remove the entire ' . DatabaseInterface::DATABASE_NAME . ' subdirectory.');
            return NULL;
        }

        # Create a log file from scratch and make them writable
        $db_path = ($dbdir == '.' ? getcwd() : $dbdir) . DIRECTORY_SEPARATOR . DatabaseInterface::DATABASE_NAME;
        if(!file_put_contents("$db_path/log", ' ') || !chmod("$db_path/log", 0666)){
            Log::addmsg(NULL, "Couldn't chmod log file: {$db_path}/log");
            return NULL;
        }

        $db = self::getDb($noid);
        if(is_null($db)){
            return NULL;
        }

        Log::logmsg($noid, $template
            ? sprintf('Creating database for template "%s".', $template)
            : sprintf('Creating database for bind-only minter.'));

        # Database info
        # yyy should be using db-> ops directly (for efficiency and?)
        #     so we can use DB_DUP flag
        self::$engine->set(GlobalsArk::_RR . "/naa", $naa);
        self::$engine->set(GlobalsArk::_RR . "/naan", $naan);
        self::$engine->set(GlobalsArk::_RR . "/subnaa", $subnaa ? : '');

        self::$engine->set(GlobalsArk::_RR . "/longterm", $term === 'long');
        self::$engine->set(GlobalsArk::_RR . "/wrap", $term === 'short');     # yyy follow through

        self::$engine->set(GlobalsArk::_RR . "/template", $template);
        self::$engine->set(GlobalsArk::_RR . "/prefix", $prefix);
        self::$engine->set(GlobalsArk::_RR . "/mask", $mask);
        self::$engine->set(GlobalsArk::_RR . "/firstpart", ($naan ? $naan . '/' : '') . $prefix);

        $add_cc = (bool)preg_match('/k$/', $mask);    # boolean answer
        self::$engine->set(GlobalsArk::_RR . "/addcheckchar", $add_cc);
        if($add_cc){
            // The template is already checked, so no error is possible.
            $repertoire = Helper::getAlphabet($template);
            self::$engine->set(GlobalsArk::_RR . "/checkrepertoire", $repertoire);
            self::$engine->set(GlobalsArk::_RR . "/checkalphabet", GlobalsArk::$alphabets[$repertoire]);
        }

        self::$engine->set(GlobalsArk::_RR . "/generator_type", $gen_type);
        self::$engine->set(GlobalsArk::_RR . "/genonly", $genonly);
        if($gen_type == 'random'){
            self::$engine->set(GlobalsArk::_RR . "/generator_random", Noid::$random_generator);
        }

        self::$engine->set(GlobalsArk::_RR . "/total", $total);
        self::$engine->set(GlobalsArk::_RR . "/padwidth", ($total == GlobalsArk::NOLIMIT ? 16 : 2) + strlen($mask));
        # yyy kludge -- padwidth of 16 enough for most lvf sorting

        # Some variables:
        #   oacounter   overall counter's current value (last value minted)
        #   oatop   overall counter's greatest possible value of counter
        #   held    total with "hold" placed
        #   queued  total currently in the queue
        self::$engine->set(GlobalsArk::_RR . "/oacounter", 0);
        self::$engine->set(GlobalsArk::_RR . "/oatop", $total);
        self::$engine->set(GlobalsArk::_RR . "/held", 0);
        self::$engine->set(GlobalsArk::_RR . "/queued", 0);

        self::$engine->set(GlobalsArk::_RR . "/fseqnum", GlobalsArk::SEQNUM_MIN);  # see queue() and mint()
        self::$engine->set(GlobalsArk::_RR . "/gseqnum", GlobalsArk::SEQNUM_MIN);  # see queue()
        self::$engine->set(GlobalsArk::_RR . "/gseqnum_date", 0);      # see queue()

        self::$engine->set(GlobalsArk::_RR . "/version", GlobalsArk::VERSION);

        # yyy should verify that a given NAAN and NAA are registered,
        #     and should offer to register them if not… ?

        # Capture the properties of this minter.
        #
        # There are seven properties, represented by a string of seven
        # capital letters or a hyphen if the property does not apply.
        # The maximal string is GRANITE (we first had GRANT, then GARNET).
        # We don't allow 'l' as an extended digit (good for minimizing
        # visual transcriptions errors), but we don't get a chance to brag
        # about that here.
        #
        # Note that on the Mohs mineral hardness scale from 1 - 10,
        # the hardest is diamonds (which are forever), but granites
        # (combinations of feldspar and quartz) are 5.5 to 7 in hardness.
        # From http://geology.about.com/library/bl/blmohsscale.htm ; see also
        # http://www.mineraltown.com/infocoleccionar/mohs_scale_of_hardness.htm
        #
        # These are far from perfect measures of identifier durability,
        # and of course they are only from the assigner's point of view.
        # For example, an alphabetical restriction doesn't guarantee
        # opaqueness, but it indicates that semantics will be limited.
        #
        # yyy document that (I)mpressionable has to do with printing, does
        #     not apply to general URLs, but does apply to phone numbers and
        #     ISBNs and ISSNs
        # yyy document that the opaqueness test is English-centric -- these
        #     measures work to some extent in English, but not in Welsh(?)
        #     or "l33t"
        # yyy document that the properties are numerous enough to look for
        #     a compact acronym, that the choice of acronym is sort of
        #     arbitrary, so (GRANITE) was chosen since it's easy to remember
        #
        # $pre and $msk are in service of the letter "A" below.
        $pre = preg_replace('/[a-z]/i', 'e', $prefix);
        $msk = preg_replace('/k/', 'e', $mask);
        $msk = preg_replace('/^ze/', 'zeeee', $msk);       # initial 'e' can become many later on

        $properties = ($naan !== '' && $naan !== '00000' ? 'G' : '-')
            . ($gen_type === 'random' ? 'R' : '-')
            # yyy substr is supposed to cut off first char
            . ($genonly && !preg_match('/eee/', $pre . substr($msk, 1)) ? 'A' : '-')
            . ($term === 'long' ? 'N' : '-')
            . ($genonly && !preg_match('/-/', $prefix) ? 'I' : '-')
            . (self::$engine->get(GlobalsArk::_RR . "/addcheckchar") ? 'T' : '-')
            // Currently, only alphabets "d", "e" and "i" are without vowels.
            . ($genonly && (preg_match('/[aeiouy]/i', $prefix) || preg_match('/[^rszdeik]/', $mask))
                ? '-' : 'E')        # Elided vowels or not
        ;
        self::$engine->set(GlobalsArk::_RR . "/properties", $properties);

        # Now figure out "where" element.
        #
        $host = gethostname();

        $cwd = $dbdir;   # by default, assuming $dbdir is absolute path
        if(substr($dbdir, 0, 1) !== '/'){
            $cwd = getcwd() . '/' . $dbdir;
        }

        # Adjust some empty values for short-term display purposes.
        #
        $naa = $naa ? : 'no Name Assigning Authority';
        $subnaa = $subnaa ? : 'no sub authority';
        $naan = $naan ? : 'no NAA Number';

        # Create a human- and machine-readable report.
        #
        $p = str_split($properties);         # split into letters
        $p = array_map(
            function($v){
                return $v == '-' ? '_ not' : '_____';
            },
            $p);
        $random_sample = NULL;          # null on purpose
        if($total == GlobalsArk::NOLIMIT){
            $random_sample = rand(0, 9); # first sample less than 10
        }
        $sample1 = self::sample($noid, $random_sample);
        if($total == GlobalsArk::NOLIMIT){
            $random_sample = rand(0, 100000); # second sample bigger
        }
        $sample2 = self::sample($noid, $random_sample);

        $htotal = $total == GlobalsArk::NOLIMIT ? 'unlimited' : Helper::formatNumber($total);
        $what = ($total == GlobalsArk::NOLIMIT ? 'unlimited' : $total)
            . ' ' . sprintf('%s identifiers of form %s', $gen_type, $template) . PHP_EOL
            . '       ' . 'A Noid minting and binding database has been created that will bind ' . PHP_EOL
            . '       ' . ($genonly ? '' : 'any identifier ') . 'and mint ' . ($total == GlobalsArk::NOLIMIT
                ? sprintf('an unbounded number of identifiers') . PHP_EOL
                . '       '
                : sprintf('%s identifiers', $htotal) . ' ')
            . sprintf('with the template "%s".', $template) . PHP_EOL
            . '       ' . sprintf('Sample identifiers would be "%s" and "%s".', $sample1, $sample2) . PHP_EOL
            . '       ' . sprintf('Minting order is %s.', $gen_type);

        $erc =
            "# Creation record for the identifier generator by " . str_replace('\\', '.', get_class(self::$engine)) . ".
            # All the logs are placed in " . $db_path . ".
            erc:
            who:       $contact
            what:      $what
            when:      " . Helper::getTemper() . "
            where:     $host:$cwd
            Version:   Noid " . GlobalsArk::VERSION . "
            Size:      " . ($total == GlobalsArk::NOLIMIT ? "unlimited" : $total) . "
            Template:  " . (!$template
                            ? '(:none)'
                            : $template . "
                   A suggested parent directory for this template is \"$synonym\".  Note:
                   separate minters need separate directories, and templates can suggest
                   short names; e.g., the template \"xz.redek\" suggests the parent directory
                   \"noid_xz4\" since identifiers are \"xz\" followed by 4 characters.") . "
            Policy:    (:$properties)
                   This minter's durability summary is (maximum possible being \"GRANITE\")
                     \"$properties\", which breaks down, property by property, as follows.
                      ^^^^^^^
                      |||||||_$p[6] (E)lided of vowels to avoid creating words by accident
                      ||||||_$p[5] (T)ranscription safe due to a generated check character
                      |||||_$p[4] (I)mpression safe from ignorable typesetter-added hyphens
                      ||||_$p[3] (N)on-reassignable in life of Name Assigning Authority
                      |||_$p[2] (A)lphabetic-run-limited to pairs to avoid acronyms
                      ||_$p[1] (R)andomly sequenced to avoid series semantics
                      |_$p[0] (G)lobally unique within a registered namespace (currently
                                 tests only ARK namespaces; apply for one at ark@cdlib.org)
            Authority: $naa | $subnaa
            NAAN:      $naan
            ";
        self::$engine->set(GlobalsArk::_RR . "/erc", $erc);

        if(!file_put_contents("$db_path/README", self::$engine->get(GlobalsArk::_RR . "/erc"))){
            return NULL;
        }
        # yyy useful for quick info on a minter from just doing 'ls NOID'??

        $report = sprintf('Created:   minter for %s', $what)
            . '  ' . sprintf('See %s/README for details.', $db_path) . PHP_EOL;

        if(empty($template)){
            self::dbclose($noid);
            return $report;
        }

        self::_init_counters($noid);
        self::dbclose($noid);
        return $report;
    }

}