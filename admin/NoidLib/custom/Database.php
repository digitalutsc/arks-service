<?php

namespace Noid\Lib\Custom;
require_once "NoidLib/custom/NoidArk.php";
require_once "NoidLib/custom/GlobalsArk.php";
require_once 'NoidLib/lib/Generator.php';
require_once 'NoidLib/lib/Helper.php';
require_once 'NoidLib/lib/Log.php';
require_once 'NoidLib/lib/Globals.php';
require_once 'NoidLib/lib/Noid.php';
require_once 'NoidLib/lib/Storage/DatabaseInterface.php';

use Noid\Lib\Generator;
use Noid\Lib\Globals;
use Noid\Lib\Helper;
use Noid\Lib\Log;
use \Exception;
use Noid\Lib\Storage\DatabaseInterface;
use Noid\Config\MysqlArkConf;

class Database
{
    /**
     * @var DatabaseInterface $engine abstracted database interface.
     *                                   added by xQ
     */
    static public $engine;

    /**
     * Allows to test the locking mechanism.
     *
     * @var int $locktest
     */
    static public $locktest = 0;

    /**
     * Locking can be "l" (a .lck file is created) or "d" (the db file itself is
     * locked). Default is "d" and "l" has not been checked.
     *
     * @var string $_db_lock
     */
    static protected $_db_lock = 'd';

    /**
     * list all Arrk database
     * @param string $name
     */
    public static function showDatabases()
    {
        $link = mysqli_connect(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd, MysqlArkConf::$mysql_dbname);

        if (!$link) {
            echo "Error: Unable to connect to MySQL." . PHP_EOL;
            echo "Debugging errno: " . mysqli_connect_errno() . PHP_EOL;
            echo "Debugging error: " . mysqli_connect_error() . PHP_EOL;
            exit;
        }


        if ($query = mysqli_query($link, "SHOW TABLES")) {

            if (!mysqli_query($link, "SET @a:='this will not work'")) {
                printf("Error: %s\n", mysqli_error($query));
            }
            $results = $query->fetch_all();
            $arkdbs = [];
            foreach ($results as $db) {
                // It starts with 'http'
                array_push($arkdbs, $db[0]);
            }
            $query->close();
        }
        mysqli_close($link);
        return $arkdbs;
    }

    /**
     * list all Arrk database
     * @param string $name
     */
    public static function showArkDatabases()
    {
        $link = mysqli_connect(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd, MysqlArkConf::$mysql_dbname);

        if (!$link) {
            echo "Error: Unable to connect to MySQL." . PHP_EOL;
            echo "Debugging errno: " . mysqli_connect_errno() . PHP_EOL;
            echo "Debugging error: " . mysqli_connect_error() . PHP_EOL;
            exit;
        }

        if ($query = mysqli_query($link, "SHOW TABLES")) {
            if (!mysqli_query($link, "SET @a:='this will not work'")) {
                printf("Error: %s\n", mysqli_error($query));
            }
            $results = $query->fetch_all();
            $arkdbs = [];
            foreach ($results as $db) {
                // It starts with 'http'
                if (!in_array($db[0], ['system', 'user'])) {
                    array_push($arkdbs, $db[0]);
                }
            }
            $query->close();
        }
        mysqli_close($link);
        return $arkdbs;
    }

    /**
     * determine the system is installed
     * @param string $name
     */
    public static function isInstalled()
    {
        $install = 0;
        try {
            $link = mysqli_connect(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd, MysqlArkConf::$mysql_dbname);
            $mandatory = ['system', 'user'];
            if (!$link) {
                if (mysqli_connect_errno() === 1049) {
                    echo "<p><strong>Error: " . mysqli_connect_error() . PHP_EOL . ". Please create the database <i>". MysqlArkConf::$mysql_dbname."</i> before proceeding.</p>";
                    exit;
                }

            }
            if ($query = mysqli_query($link, "SHOW TABLES")) {
                if (!mysqli_query($link, "SET @a:='this will not work'")) {
                    printf("Error: %s\n", mysqli_error($query));
                    return false;
                }
                $results = $query->fetch_all();
                if (count($results) >= 2) {
                    foreach ($results as $db) {
                        // It starts with 'http'
                        if (in_array($db[0], $mandatory)) {
                            $install++;
                        }
                    }
                }
                $query->close();
            }
            mysqli_close($link);
            return $install == count($mandatory);
        }
        catch(\Exception $ex) {
            return false;
        }
    }

    /**
     * Get Org registered info
     */
    public static function getReCAPTCHA_sitekey()
    {
        $link = mysqli_connect(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd, MysqlArkConf::$mysql_dbname);

        if (!$link) {
            echo "Error: Unable to connect to MySQL." . PHP_EOL;
            echo "Debugging errno: " . mysqli_connect_errno() . PHP_EOL;
            echo "Debugging error: " . mysqli_connect_error() . PHP_EOL;
            exit;
        }
        if ($query = mysqli_query($link, "SELECT _value FROM `system` WHERE _KEY = 'reCAPTCHA_sitekey'")) {

            if (!mysqli_query($link, "SET @a:='this will not work'")) {
                printf("Error: %s\n", mysqli_error($query));
            }
            $results = $query->fetch_assoc();
            if (count($results) > 0) {
                return $results;
            }

            $query->close();
        }
        mysqli_close($link);
        return false;
    }

    /**
     * Get Org registered info
     */
    public static function getReCAPTCHA_secret()
    {
        $link = mysqli_connect(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd, MysqlArkConf::$mysql_dbname);

        if (!$link) {
            echo "Error: Unable to connect to MySQL." . PHP_EOL;
            echo "Debugging errno: " . mysqli_connect_errno() . PHP_EOL;
            echo "Debugging error: " . mysqli_connect_error() . PHP_EOL;
            exit;
        }
        if ($query = mysqli_query($link, "SELECT _value FROM `system` WHERE _KEY = 'reCAPTCHA_secretkey'")) {

            if (!mysqli_query($link, "SET @a:='this will not work'")) {
                printf("Error: %s\n", mysqli_error($query));
            }
            $results = $query->fetch_assoc();
            if (count($results) > 0) {
                return $results;
            }

            $query->close();
        }
        mysqli_close($link);
        return false;
    }

    /**
     * Get Org registered info
     */
    public static function getAdminEmail()
    {
        $link = mysqli_connect(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd, MysqlArkConf::$mysql_dbname);

        if (!$link) {
            echo "Error: Unable to connect to MySQL." . PHP_EOL;
            echo "Debugging errno: " . mysqli_connect_errno() . PHP_EOL;
            echo "Debugging error: " . mysqli_connect_error() . PHP_EOL;
            exit;
        }
        if ($query = mysqli_query($link, "SELECT _value FROM `system` WHERE _KEY = 'adminEmail'")) {

            if (!mysqli_query($link, "SET @a:='this will not work'")) {
                printf("Error: %s\n", mysqli_error($query));
            }
            $results = $query->fetch_assoc();
            if (count($results) > 0) {
                return $results;
            }

            $query->close();
        }
        mysqli_close($link);
        return false;
    }

    /**
     * Backup the database before any bulk binding
     */
    public static function backupArkDatabase()
    {
        if (MysqlArkConf::$backup_method == 1) {
            self::backup_tables(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd, MysqlArkConf::$mysql_dbname);
        }
        else if (MysqlArkConf::$backup_method == 2) {
            self::mysqldump();
        }
    }

    /**
     * Backup the database by using mysqldump
     */
    public static function mysqldump() {
        error_log(print_r("backupArkDatabase", TRUE), 0);
        if (!file_exists(getcwd() . "/db/backup")) {
            mkdir(getcwd() . "/db/backup", 0775);
        }
        $backup_file = MysqlArkConf::$path_db_backup . 'ark-db-backup-' . time() . '.sql';
        $cmd = MysqlArkConf::$mysqldump . " --user=".MysqlArkConf::$mysql_user." --password=".MysqlArkConf::$mysql_passwd." --host=".MysqlArkConf::$mysql_host." ".MysqlArkConf::$mysql_dbname." > ".$backup_file." 2>&1";
        error_log(print_r($cmd, TRUE), 0);
        $output = shell_exec($cmd);

        error_log(print_r($output, TRUE), 0);
    }

    /**
     * Back up the database by PHP
     * https://stackoverflow.com/questions/13659534/backup-mysql-tables-with-php
     * @param $host
     * @param $user
     * @param $pass
     * @param $name
     * @param string $tables
     * @return string
     */
    public static function &backup_tables($host, $user, $pass, $name, $tables = '*')
    {
        // save to file
        $backup_file = MysqlArkConf::$path_db_backup . 'ark-db-backup-' . time() . '.sql';
        $handle = fopen($backup_file, 'w+');
        
        $data = "\n/*---------------------------------------------------------------" .
            "\n  ARK Services DB BACKUP " . date("d.m.Y H:i") . " " .
            "\n  HOST: {$host}" .
            "\n  DATABASE: {$name}" .
            "\n  TABLES: {$tables}" .
            "\n  ---------------------------------------------------------------*/\n";
        fwrite($handle, $data);
        $link = mysqli_connect($host, $user, $pass);
        mysqli_select_db($link, $name);
        mysqli_query($link, "SET NAMES `utf8` COLLATE `utf8_general_ci`"); // Unicode

        if ($tables == '*') { //get all of the tables
            $tables = array();
            $result = mysqli_query($link, "SHOW TABLES");
            while ($row = mysqli_fetch_row($result)) {
                $tables[] = $row[0];
            }
        } else {
            $tables = is_array($tables) ? $tables : explode(',', $tables);
        }

        foreach ($tables as $table) {
            $data .= "\n/*---------------------------------------------------------------" .
                "\n  TABLE: `{$table}`" .
                "\n  ---------------------------------------------------------------*/\n";
            $data .= "DROP TABLE IF EXISTS `{$table}`;\n";
            fwrite($handle, $data);
            $res = mysqli_query($link, "SHOW CREATE TABLE `{$table}`");
            $row = mysqli_fetch_row($res);
            $data .= $row[1] . ";\n";
            fwrite($handle, $data);
            $result = mysqli_query($link, "SELECT * FROM `{$table}`");
            $num_rows = mysqli_num_rows($result);

            if ($num_rows > 0) {
                $vals = array();
                $z = 0;
                for ($i = 0; $i < $num_rows; $i++) {
                    $items = mysqli_fetch_row($result);
                    $vals[$z] = "(";
                    for ($j = 0; $j < count($items); $j++) {
                        if (isset($items[$j])) {
                            $vals[$z] .= "'" . mysqli_real_escape_string($link, $items[$j]) . "'";
                        } else {
                            $vals[$z] .= "NULL";
                        }
                        if ($j < (count($items) - 1)) {
                            $vals[$z] .= ",";
                        }
                    }
                    $vals[$z] .= ")";
                    $z++;
                }
                $data .= "INSERT INTO `{$table}` VALUES ";
                $data .= "  " . implode(";\nINSERT INTO `{$table}` VALUES ", $vals) . ";\n";
                fwrite($handle, $data);
            }
        }
        mysqli_close($link);
        fclose($handle);
    }

    /**
     * Get Org registered info
     */
    public static function getOrganization()
    {
        $link = mysqli_connect(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd, MysqlArkConf::$mysql_dbname);

        if (!$link) {
            echo "Error: Unable to connect to MySQL." . PHP_EOL;
            echo "Debugging errno: " . mysqli_connect_errno() . PHP_EOL;
            echo "Debugging error: " . mysqli_connect_error() . PHP_EOL;
            exit;
        }
        if ($query = mysqli_query($link, "SELECT * FROM `system`")) {

            if (!mysqli_query($link, "SET @a:='this will not work'")) {
                printf("Error: %s\n", mysqli_error($query));
            }
            $results = $query->fetch_all();
            if (count($results) > 0) {
                return $results;
            }

            $query->close();
        }
        mysqli_close($link);
        return false;
    }

  /**
   * Get Org registered info
   */
  public static function getArkURL()
  {
    $link = mysqli_connect(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd, MysqlArkConf::$mysql_dbname);

    if (!$link) {
      echo "Error: Unable to connect to MySQL." . PHP_EOL;
      echo "Debugging errno: " . mysqli_connect_errno() . PHP_EOL;
      echo "Debugging error: " . mysqli_connect_error() . PHP_EOL;
      exit;
    }
    if ($query = mysqli_query($link, "SELECT _value FROM `system` where _key= 'Organization Website'")) {

      if (!mysqli_query($link, "SET @a:='this will not work'")) {
        printf("Error: %s\n", mysqli_error($query));
      }
      $results = $query->fetch_all();
      if (count($results) > 0) {
        return $results[0][0];
      }

      $query->close();
    }
    mysqli_close($link);
    return false;
  }

    /**
     * verify authenticated to run POST method
     * @param String $password
     * @return bool
     */
    public static function isAuth(string $password)
    {
        $encryptPasswd = secureEncryption($password, "VUQY%IdGWlBT!83YCM6TtY5X-uIYv)i1AEyk67VpusyCDXZW0", 2734025702752005);

        $link = mysqli_connect(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd, MysqlArkConf::$mysql_dbname);

        if (!$link) {
            echo "Error: Unable to connect to MySQL." . PHP_EOL;
            echo "Debugging errno: " . mysqli_connect_errno() . PHP_EOL;
            echo "Debugging error: " . mysqli_connect_error() . PHP_EOL;
            exit;
        }
        $auth = false;
        if ($query = mysqli_query($link, "SELECT * FROM `user` WHERE `pasword` = '$encryptPasswd'")) {

            if (!mysqli_query($link, "SET @a:='this will not work'")) {
                printf("Error: %s\n", mysqli_error($query));
            }
            $results = $query->fetch_all();

            if (count($results) > 0) {
                $auth = true;
            }

            $query->close();
        }
        mysqli_close($link);
        return $auth;
    }

    /**
     * Check ark database name is existed/created
     * @param String $dbname
     * @return bool
     */
    static public function exist(string $dbname)
    {
        $dbs = self::showDatabases();
        $existed = false;
        foreach ($dbs as $db) {
            if (strcmp($dbname, $db) === 0) {
                $existed = true;
                break;
            }
        }
        return $existed;
    }

    /**
     * Update database settings
     * @param $dbname
     * @param $field
     * @param null $value
     */
    public static function dbupdatesetting($dbname, $dbdir, $field, $value) {
        $noid = self::dbopen($dbname, $dbdir, DatabaseInterface::DB_WRITE);
        self::$engine->set(GlobalsArk::_RR . "/$field", $value);
        self::dbclose($noid);
    }

    /**
     * @param $dbdir
     * @param $contact
     * @param null $template
     * @param string $term
     * @param string $naan Name Assigning Authority Number
     * @param string $naa The NAA argument is the character string equivalent for the NAAN
     * @param string $subnaa SubNAA argument is also a character string, but is a locally determined and possibly structured subauthority string (e.g., "oac", "ucb/dpg", "practice_area") that is not globally registered
     * @return string|null
     */
    static public function dbcreate($dbname,
                                    $dbdir,
                                    $contact,
                                    $prefix,
                                    $template = NULL,
                                    $term = '-',
                                    $naan = '',
                                    $naa = '',
                                    $subnaa = '')
    {
        NoidArk::init($dbname);

        $total = NULL;
        $noid = NULL;

        $mask = NULL;
        $gen_type = NULL;
        $msg = NULL;
        $genonly = NULL;
        if (is_null($template)) {
            $genonly = 0;
            $template = '.zd';
        } else {
            $genonly = 1;           # not generated ids only
        }

        //$total = Helper::parseTemplate($template, $prefix, $mask, $gen_type, $msg);
        $total = Helper::parseTemplate($prefix . $template, $prefix, $mask, $gen_type, $msg);
        if (!$total) {
            Log::addmsg($noid, $msg);
            return NULL;
        }
        $synonym = 'noid' . ($genonly ? '_' . $msg : 'any');

        # Type check various parameters.
        #
        if (empty($contact) || trim($contact) == '') {
            Log::addmsg($noid, sprintf('error: contact (%s) must be non-empty.', $contact));
            return NULL;
        }

        $term = $term ?: '-';
        if (!in_array($term, array('long', 'medium', 'short', '-'))) {
            Log::addmsg($noid, sprintf('error: term (%s) must be either "long", "medium", "-", or "short".', $term));
            return NULL;
        }

        $naa = (string)$naa;
        $naan = (string)$naan;
        $subnaa = (string)$subnaa;

        if ($term === 'long'
            && (!strlen(trim($naan)) || !strlen(trim($naa)) || !strlen(trim($subnaa)))
        ) {
            Log::addmsg($noid, sprintf('error: longterm identifiers require an NAA Number, NAA, and SubNAA.'));
            return NULL;
        }
        # xxx should be able to check naa and naan live against registry
        # yyy code should invite to apply for NAAN by email to ark@cdlib.org
        # yyy ARK only? why not DOI/handle?
        if ($term === 'long' && !preg_match('/\d\d\d\d\d/', $naan)) {
            Log::addmsg($noid, sprintf('error: term of "long" requires a 5-digit NAAN (00000 if none), and non-empty string values for NAA and SubNAA.'));
            return NULL;
        }

        $noid = self::dbopen($dbname, $dbdir, DatabaseInterface::DB_CREATE);
        if (!$noid) {
            Log::addmsg(NULL, "error: a NOID database can not be created in: " . $dbdir . "." . PHP_EOL
                . "\t" . 'To permit creation of a new minter, rename' . PHP_EOL
                . "\t" . 'or remove the entire ' . $dbname . ' subdirectory.');
            return NULL;
        }

        # Create a log file from scratch and make them writable
        $db_path = ($dbdir == '.' ? getcwd() : $dbdir) . DIRECTORY_SEPARATOR . $dbname;
        if (!file_put_contents("$db_path/log", ' ') || !chmod("$db_path/log", 0666)) {
            Log::addmsg(NULL, "Couldn't chmod log file: {$db_path}/log");
            return NULL;
        }

        $db = self::getDb($noid);
        if (is_null($db)) {
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
        self::$engine->set(GlobalsArk::_RR . "/subnaa", $subnaa ?: '');

        self::$engine->set(GlobalsArk::_RR . "/longterm", $term === 'long');
        self::$engine->set(GlobalsArk::_RR . "/wrap", $term === 'short');     # yyy follow through

        self::$engine->set(GlobalsArk::_RR . "/template", $template);
        self::$engine->set(GlobalsArk::_RR . "/prefix", $prefix);
        self::$engine->set(GlobalsArk::_RR . "/mask", $mask);
        self::$engine->set(GlobalsArk::_RR . "/firstpart", ($naan ? $naan . '/' : '') . $prefix);

        $add_cc = (bool)preg_match('/k$/', $mask);    # boolean answer
        self::$engine->set(GlobalsArk::_RR . "/addcheckchar", $add_cc);
        if ($add_cc) {
            // The template is already checked, so no error is possible.
            $repertoire = Helper::getAlphabet($template);
            self::$engine->set(GlobalsArk::_RR . "/checkrepertoire", $repertoire);
            self::$engine->set(GlobalsArk::_RR . "/checkalphabet", GlobalsArk::$alphabets[$repertoire]);
        }

        self::$engine->set(GlobalsArk::_RR . "/generator_type", $gen_type);
        self::$engine->set(GlobalsArk::_RR . "/genonly", $genonly);
        if ($gen_type == 'random') {
            self::$engine->set(GlobalsArk::_RR . "/generator_random", NoidArk::$random_generator);
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
        if (substr($dbdir, 0, 1) !== '/') {
            $cwd = getcwd() . '/' . $dbdir;
        }

        # Adjust some empty values for short-term display purposes.
        #
        $naa = $naa ?: 'no Name Assigning Authority';
        $subnaa = $subnaa ?: 'no sub authority';
        $naan = $naan ?: 'no NAA Number';

        # Create a human- and machine-readable report.
        #
        $p = str_split($properties);         # split into letters
        $p = array_map(
            function ($v) {
                return $v == '-' ? '_ not' : '_____';
            },
            $p);
        $random_sample = NULL;          # null on purpose
        if ($total == GlobalsArk::NOLIMIT) {
            $random_sample = rand(0, 9); # first sample less than 10
        }
        $sample1 = self::sample($noid, $random_sample);
        if ($total == GlobalsArk::NOLIMIT) {
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

        if (!file_put_contents("$db_path/README", self::$engine->get(GlobalsArk::_RR . "/erc"))) {
            return NULL;
        }
        # yyy useful for quick info on a minter from just doing 'ls NOID'??

        $report = sprintf('Created:   minter for %s', $what)
            . '  ' . sprintf('See %s/README for details.', $db_path) . PHP_EOL;

        if (empty($template)) {
            self::dbclose($noid);
            return $report;
        }

        self::_init_counters($noid);
        self::dbclose($noid);
        return $report;
    }


    /**
     * Open a database in the specified mode and returns its full name.
     *
     * @param string $dbdir
     * @param string $flags
     * Can be DB_RDONLY, DB_CREATE, or DB_WRITE (the default).
     * Support for perl script: DB_RDONLY, DB_CREAT and DB_RDWR, without bit
     * checking. Other flags are not managed.
     *
     * @return string
     * @throws Exception
     * @internal The Perl script returns noid: a listref.
     * @todo     Berkeley specific environment flags are not supported.
     *
     */
    static public function dbopen($dbname, $dbdir, $flags = DatabaseInterface::DB_WRITE)
    {
        NoidArk::init($dbname);

        // For compatibility purpose between perl and php.
        switch ($flags) {
            case DatabaseInterface::DB_CREATE:
            case DatabaseInterface::DB_RDONLY:
            case DatabaseInterface::DB_WRITE:
                break;
            default:
                Log::addmsg(NULL, sprintf('"%s" is not a regular flag', $flags));
                return NULL;
        }

        $envhome = $dbdir . DIRECTORY_SEPARATOR . $dbname . DIRECTORY_SEPARATOR;
        if (!is_dir($envhome) && !mkdir($envhome, 0755, TRUE)) {
            $error = error_get_last();
            throw new Exception(sprintf("error: couldn't create database directory %s: %s", $envhome, $error['message']));
        }

        $mode = $flags . self::$_db_lock;

        $db = @self::$engine->open($dbdir, $mode);
        if ($db === FALSE) {
            Log::addmsg(NULL, sprintf('Failed to open database in directory "%s".', $dbdir));
            return NULL;
        }

        # yyy to test: can we now open more than one noid at once?
        if (!is_dir($envhome)) {
            Log::addmsg(NULL, sprintf('%s not a directory', $envhome));
            return NULL;
        }

        # yyy probably these envflags are overkill right now
        $_GLOBAL['envargs'] = array();
        if ($flags == DatabaseInterface::DB_CREATE) {
            $_GLOBAL['envargs']['-Home'] = $envhome;
            $_GLOBAL['envargs']['-Verbose'] = 1;
        }

        # If it exists and is writable, use log file to inscribe the errors.
        $logfile = $envhome . 'log';
        $logfhandle = fopen($logfile, 'a');
        $log_opened = $logfhandle !== FALSE;
        # yyy should we complain if can't open log file?

        $noid = $dbdir;

        # yyy how to set error code or return string?
        #   or die("Can't open database file: $!\n");
        Globals::$open_tab['database'][$noid] = $db;
        Globals::$open_tab['msg'][$noid] = '';
        Globals::$open_tab['log'][$noid] = $log_opened ? $logfhandle : NULL;

        if (self::$locktest) {
            print sprintf('locktest: holding lock for %s seconds…', self::$locktest) . PHP_EOL;
            sleep(self::$locktest);
        }

        return $noid;
    }

    /**
     * Close database.
     *
     * @param string $noid
     *
     * @return void
     * @throws Exception
     */
    static public function dbclose($noid)
    {
        $db = self::getDb($noid);
        if (is_null($db)) {
            return;
        }

        unset(Globals::$open_tab['msg'][$noid]);
        if (!empty(Globals::$open_tab['log'][$noid])) {
            fclose(Globals::$open_tab['log'][$noid]);
        }
        self::$engine->close();
        /*
        // Let go of lock.
        close NOIDLOCK;
        */
    }

    /**
     * Import data from other source.
     *
     * @param string $dbdir
     * @param string $src_type
     *
     * @return bool
     * @throws Exception
     */
    static public function dbimport($dbname, $dbdir, $src_type)
    {
        // Assume followings
        // 1. both source and destination db are placed in same directory.
        // 2. their db names are same, and the table name (for Mysql) and file name (for Berkeley or XML) too.

        // initialize this database.
        NoidArk::init($dbname);
        if (!self::$engine->open($dbdir, DatabaseInterface::DB_WRITE))
            throw new Exception('The destination database is not exist.' . PHP_EOL);

        // initialize the source db
        $db_class = Globals::DB_TYPES[$src_type];
        $db_class_file = preg_replace('/(^.*\\\\)/', '', $db_class);
        require_once 'Storage' . DIRECTORY_SEPARATOR . $db_class_file . '.php';
        /** @var DatabaseInterface $src_engine */
        $src_engine = new $db_class();
        if (!$src_engine->open($dbdir, DatabaseInterface::DB_RDONLY))
            throw new Exception('The source database is not exist in ' . $dbdir . PHP_EOL);

        // do import!
        $is_ok = self::$engine->import($src_engine);
        $src_engine->close();
        self::$engine->close();

        return $is_ok;
    }

    /**
     * Report values according to level.
     *
     * @param string $noid
     * @param string $level Possible values:
     *                      - "brief" (default): user vals and interesting admin vals
     *                      - "full": user vals and all admin vals
     *                      - "dump": all vals, including all identifier bindings
     *
     * @return int 0 (error) or 1 (success)
     * @throws Exception
     */
    static public function dbinfo($dbname, $noid, $level = 'brief')
    {
        NoidArk::init($dbname);

        $db = self::getDb($noid);
        if (is_null($db)) {
            return 0;
        }

        if ($level === 'dump') {
            // Re-fetch from the true first key: data are ordered alphabetically
            // and some identifier may be set before the root ":", like numbers.
            $values = self::$engine->get_range('');
            foreach ($values as $key => $value) {
                print $key . ': ' . $value . PHP_EOL;
            }
            return 1;
        }

        $userValues = self::$engine->get_range(Globals::_RR . "/" . Globals::_RR . "/");
        if ($userValues) {
            print 'User Assigned Values:' . PHP_EOL;
            foreach ($userValues as $key => $value) {
                print '  ' . $key . ': ' . $value . PHP_EOL;
            }
            print PHP_EOL;
        }

        print 'Admin Values:' . PHP_EOL;
        $values = self::$engine->get_range(Globals::_RR . "/");
        if (is_null($values)) {
            Log::addmsg($noid, sprintf('No values returned by the database.'));
            return 0;
        }
        foreach ($values as $key => $value) {
            if ($level === 'full'
                || !preg_match('|^' . preg_quote(Globals::_RR . "/c", '|') . '\d|', $key)
                && strpos($key, Globals::_RR . "/" . Globals::_RR . "/") !== 0
                && strpos($key, Globals::_RR . "/saclist") !== 0
                && strpos($key, Globals::_RR . "/recycle/") !== 0
            ) {
                print '  ' . $key . ': ' . $value . PHP_EOL;
            }
        }
        print PHP_EOL;

        return 1;
    }

    /**
     * Return the database handle for the specified noid.
     *
     * @param string $noid Full path to the database file.
     *
     * @return resource|NULL Handle to the database resource, else null.
     * @throws Exception
     */
    static public function getDb($noid)
    {
        if (!isset(Globals::$open_tab['database'][$noid])) {
            Log::addmsg($noid, sprintf('error: Database "%s" is not opened.', $noid));
            return NULL;
        }
        $db = Globals::$open_tab['database'][$noid];
        if (!is_resource($db) && !is_object($db)) {
            Log::addmsg($noid, sprintf('error: Access to database "%s" failed .', $noid));
            return NULL;
        }
        return $db;
    }

    /**
     * BerkeleyDB features.  For now, lock before tie(), unlock after untie().
     *
     * @return int 1.
     * @todo eventually we would like to do fancy fine-grained locking with
     */
    static public function _dblock()
    {
        // Placeholder.
        return 1;
    }

    /**
     * BerkeleyDB features.  For now, lock before tie(), unlock after untie().
     *
     * @return int 1.
     * @todo eventually we would like to do fancy fine-grained locking with
     */
    static public function _dbunlock()
    {
        // Placeholder.
        return 1;
    }

    /**
     * Call with number of seconds to sleep at end of each open.
     * This exists only for the purpose of testing the locking mechanism.
     *
     * @param string $sleepvalue
     *
     * @return int 1
     * @throws Exception
     */
    static public function locktest($dbname, $sleepvalue)
    {
        NoidArk::init($dbname);

        // Set global variable for locktest.
        self::$locktest = $sleepvalue;
        return 1;
    }

    /**
     * Initialize counters.
     *
     * @param string $noid
     *
     * @return void
     * @throws Exception
     */
    static public function _init_counters($noid)
    {
        $db = self::getDb($noid);
        if (is_null($db)) {
            return;
        }

        # Variables:
        #   oacounter   overall counter's current value (last value minted)
        #   saclist (sub) active counters list
        #   siclist (sub) inactive counters list
        #   c$n/value   subcounter name's ($n) value
        #   c$n/top subcounter name's greatest possible value

        self::_dblock();

        self::$engine->set(Globals::_RR . "/oacounter", 0);
        $total = self::$engine->get(Globals::_RR . "/total");

        $maxcounters = 293;      # prime, a little more than 29*10
        #
        # Using a prime under the theory (unverified) that it may help even
        # out distribution across the more significant digits of generated
        # identifiers.  In this way, for example, a method for mapping an
        # identifier to a pathname (eg, fk9tmb35x -> fk/9t/mb/35/x/, which
        # could be a directory holding all files related to the named
        # object), would result in a reasonably balanced filesystem tree
        # -- no subdirectories too unevenly loaded.  That's the hope anyway.

        self::$engine->set(Globals::_RR . "/percounter",
            intval($total / $maxcounters + 1) # round up to be > 0
        );                              # max per counter, last has fewer

        $n = 0;
        $t = $total;
        $pctr = self::$engine->get(Globals::_RR . "/percounter");
        $saclist = '';
        while ($t > 0) {
            self::$engine->set(Globals::_RR . "/c$n/top", $t >= $pctr ? $pctr : $t);
            self::$engine->set(Globals::_RR . "/c$n/value", 0);       # yyy or 1?
            $saclist .= "c$n ";
            $t -= $pctr;
            $n++;
        }
        self::$engine->set(Globals::_RR . "/saclist", $saclist);
        self::$engine->set(Globals::_RR . "/siclist", '');
//			$n--; // commented by xQ

        self::_dbunlock();
    }

    /**
     * Generate a sample id for testing purposes.
     *
     * @param string $noid
     * @param int $num
     *
     * @return string
     * @throws Exception
     */
    static public function sample($noid, $num = NULL)
    {
        $db = self::getDb($noid);
        if (is_null($db)) {
            return NULL;
        }

        $upper = NULL;
        if (is_null($num)) {
            $upper = self::$engine->get(Globals::_RR . "/total");
            if ($upper == Globals::NOLIMIT) {
                $upper = 100000;
            }
            $num = rand(0, $upper - 1);
        }
        $mask = self::$engine->get(Globals::_RR . "/mask");
        $firstpart = self::$engine->get(Globals::_RR . "/firstpart");
        $result = $firstpart . Generator::n2xdig($num, $mask);

        if (self::$engine->get(Globals::_RR . "/addcheckchar")) {
            $template = self::$engine->get(Globals::_RR . "/template");
            $repertoire = Helper::getAlphabet($template);
            return Helper::checkChar($result, $repertoire);
        }

        return $result;
    }

    /**
     * Scopes.
     *
     * @param string $noid
     *
     * @return int 1
     * @throws Exception
     */
    static public function scope($dbname, $noid)
    {
        NoidArk::init($dbname);

        $db = self::getDb($noid);
        if (is_null($db)) {
            return 0;
        }

        $template = self::$engine->get(Globals::_RR . "/template");
        if (!$template) {
            print 'This minter does not generate identifiers, but it does accept user-defined identifier and element bindings.' . PHP_EOL;
        }
        $total = self::$engine->get(Globals::_RR . "/total");
        $totalstr = Helper::formatNumber($total);
        $naan = self::$engine->get(Globals::_RR . "/naan") ?: '';
        if ($naan) {
            $naan .= '/';
        }

        $prefix = self::$engine->get(Globals::_RR . "/prefix");
        $mask = self::$engine->get(Globals::_RR . "/mask");
        $gen_type = self::$engine->get(Globals::_RR . "/generator_type");

        print sprintf('Template %s will yield %s %s unique ids',
                $template, $total < 0 ? 'an unbounded number of' : $totalstr, $gen_type) . PHP_EOL;
        $tminus1 = $total < 0 ? 987654321 : $total - 1;

        # See if we need to compute a check character.
        $results = array(0 => NULL, 1 => NULL, 2 => NULL, $tminus1 => NULL);
        if (28 < $total - 1) {
            $results[28] = NULL;
        }
        if (29 < $total - 1) {
            $results[29] = NULL;
        }
        foreach ($results as $n => &$xdig) {
            $xdig = $naan . Generator::n2xdig($n, $mask);
            if (self::$engine->get(Globals::_RR . "/addcheckchar")) {
                $xdig = Helper::checkChar($xdig, $prefix . '.' . $mask);
            }
        }
        unset($xdig);

        print 'in the range ' . $results[0] . ', ' . $results[1] . ', ' . $results[2];
        if (28 < $total - 1) {
            print ', …, ' . $results[28];
        }
        if (29 < $total - 1) {
            print ', ' . $results[29];
        }
        print ', … up to ' . $results[$tminus1]
            . ($total < 0 ? ' and beyond.' : '.')
            . PHP_EOL;
        if (substr($mask, 0, 1) !== 'r') {
            return 1;
        }
        print 'A sampling of random values (may already be in use): ';
        for ($i = 0; $i < 5; $i++) {
            print self::sample($noid) . ' ';
        }
        print PHP_EOL;
        return 1;
    }
}
