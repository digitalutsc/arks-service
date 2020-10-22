<?php
/**
 * Base library container.
 *
 * User: Hawk Johns
 * Date: 12/27/2018
 * Time: 08:57
 */

namespace Noid\Lib;

use \Exception;

require_once 'Globals.php';

class Helper{
	/**
	 * Return local date/time stamp in TEMPER format.  Use supplied time (in seconds)
	 * if any, or the current time.
	 *
	 * @param int $time
	 *
	 * @return string
	 */
	static public function getTemper($time = NULL)
	{
		return strftime('%Y%m%d%H%M%S', $time ? : time());
	}

	/**
	 * Return printable form of an integer after adding commas to separate
	 * groups of 3 digits.
	 *
	 * @param int $num
	 *
	 * @return string
	 */
	static public function formatNumber($num)
	{
		return number_format($num);
	}

	/**
	 * Compute check character for given identifier.  If identifier ends in '+'
	 * (plus), replace it with a check character computed from the preceding chars,
	 * and return the modified identifier.  If not, isolate the last char and
	 * compute a check character using the preceding chars; return the original
	 * identifier if the computed char matches the isolated char, or null if not.
	 *
	 * User explanation:  check digits help systems to catch transcription
	 * errors that users might not be aware of upon retrieval; while users
	 * often have other knowledge with which to determine that the wrong
	 * retrieval occurred, this error is sometimes not readily apparent.
	 * Check digits reduce the chances of this kind of error.
	 *
	 * @todo ask Steve Silberstein (of III) about check digits?
	 *
	 * @param string $id
	 * @param string $alphabet The label used for the alphabet to check against.
	 *                         The alphabet must contain all characters of all repertoires used. The
	 *                         argument can be the repertoire itself (more than one letter, like in
	 *                         scope()). Default to "e" for compatibility with the Perl script, that
	 *                         uses only the mask "[de]+".
	 *
	 * @return string|null
	 * @throws Exception
	 */
	static public function checkChar($id, $alphabet = 'e')
	{
		if(strlen($id) == 0){
			return NULL;
		}

		if(empty($alphabet)){
			return NULL;
		}

		// Check if the argument is the repertoire.
		if(strlen($alphabet) == 1){
			if(!isset(Globals::$alphabets[$alphabet])){
				return NULL;
			}
			$repertoire = $alphabet;
			$alphabet = Globals::$alphabets[$repertoire];
		}
		// The argument is the alphabet itself.
		else{
			$repertoire = array_search($alphabet, Globals::$alphabets);
			if(empty($repertoire)){
				return NULL;
			}
		}

		$last_char = substr($id, -1);
		$id = substr($id, 0, -1);
		$pos = 1;
		$sum = 0;
		foreach(str_split($id) as $c){
			# if character is null, it's ordinal value is zero
			if(strlen($c) > 0){
				$sum += $pos * strpos($alphabet, $c);
			}
			$pos++;
		}
		$checkchar = substr($alphabet, $sum % strlen($alphabet), 1);
		# print 'RADIX=' . strlen($alphabet) . ', mod=' . $sum % strlen($alphabet) . PHP_EOL;
		if($last_char === '+' || $last_char === $checkchar){
			return $id . $checkchar;
		}
		# must be request to check, but failed match
		# xxx test if check char changes on permutations
		# XXX include test of length to make sure < than 29 (R) chars long
		# yyy will this work for doi/handles?
		return NULL;
	}

	/**
	 * Helper to determine the repertoire of the check character, that is the
	 * shortest alphabet that contains all characters used in the template,
	 * prefix included.
	 *
	 * For compatibility purpose with the Perl script, the templates where the
	 * mask is "[de]+" are an exception and exclude the prefix, so the check
	 * repertoire is "e". The prefix isn't checked here but in parse_template().
	 *
	 * @param $template
	 *
	 * @return string|bool The label of the alphabet, or true if the template
	 * doesn't require a check character, or false if error.
	 */
	static public function getAlphabet($template)
	{
		# Confirm well-formedness of $mask before proceeding.
		if(!preg_match('/^([^\.]*)\.([rsz][' . Globals::$repertoires . ']+k?)$/', $template, $matches)){
			return FALSE;
		}
		$prefix = isset($matches[1]) ? $matches[1] : '';
		$mask = isset($matches[2]) ? $matches[2] : '';
		if(substr($mask, -1) !== 'k'){
			return TRUE;
		}

		// For compatibility purpose with Perl script, only "e" is allowed for
		// masks with "d" and "e" exclusively. The prefix is not checked here.
		if(preg_match('/^.[de]+k$/', $mask)){
			return 'e';
		}

		// Get the shortest alphabet. There are some subtleties ("x" has no "x",
		// "E has no "0"…), so a full check is needed.
		$allCharacters = $prefix;
		foreach(str_split(substr($mask, 1, strlen($mask) - 2)) as $c){
			$allCharacters .= Globals::$alphabets[Globals::$alphabetChecks[$c]];
		}
		// Deduplicate characters.
		$allCharacters = count_chars($allCharacters, 3);

		// Get the smallest repertoire with all characters.
		foreach(array_unique(Globals::$alphabetChecks) as $repertoire){
			if(preg_match('/^[' . preg_quote(Globals::$alphabets[$repertoire], '/') . ']+$/', $allCharacters)){
				return $repertoire;
			}
		}

		return FALSE;
	}

	/**
	 * Reads template looking for errors and returns the total number of
	 * identifiers that it is capable of generating, using NOLIMIT to mean
	 * indefinite (unbounded).  Returns 0 on error.  Variables $prefix,
	 * $mask, and $generator_type are output parameters.
	 *
	 * $message will always be set; 0 return with error, 1 return with synonym
	 *
	 * @todo templates should probably have names, eg, jk##.. could be jk4
	 * or jk22, as in "./noid testdb/jk4 <command> … "
	 *
	 * @param string $template
	 * @param string $prefix
	 * @param string $mask
	 * @param string $gen_type
	 * @param string $message
	 *
	 * @return int -1 for no limit, 0 for error, else the total.
	 * @throws Exception
	 */
	static public function parseTemplate($template, &$prefix, &$mask, &$gen_type, &$message)
	{
		$msg = &$message;   # so we can modify $message argument easily

		$dirname = NULL;
		$msg = '';

		# Strip final spaces and slashes.  If there's a pathname,
		# save directory and final component separately.
		#
		$template = $template ? : '';
		$template = preg_replace('|[/\s]+$|', '', $template);       # strip final spaces or slashes
		preg_match('|^(.*/)?([^/]+)$|', $template, $matches);

//			$dirname = isset($matches[1]) ? $matches[1] : '';  # make sure $dirname is defined
		$template = isset($matches[2]) ? $matches[2] : '';

		if(empty($template) || $template === '-'){
			$msg = 'parse_template: no minting possible.';
			$prefix = $mask = $gen_type = '';
			return Globals::NOLIMIT;
		}
		if(strpos($template, '.') === FALSE){
			$msg = 'parse_template: a template requires a "." to separate the prefix and the mask.'
				. " - can't generate identifiers.";
			return 0;
		}
		if(!preg_match('/^([^\.]*)\.(\w+)/', $template, $matches)){
			$msg = "parse_template: no template mask - can't generate identifiers.";
			return 0;
		}
		$prefix = isset($matches[1]) ? $matches[1] : '';
		$mask = isset($matches[2]) ? $matches[2] : '';

		if(!preg_match('/^[rsz]/', $mask)){
			$msg = 'parse_template: mask must begin with one of the letters' . PHP_EOL
				. '"r" (random), "s" (sequential), or "z" (sequential unlimited).';
			return 0;
		}

		if(!preg_match('/^.[^k]+k?$/', $mask)){
			$msg = 'parse_template: exactly one check character (k) is allowed, and it may only appear at the end of a string of one or more mask characters.';
			return 0;
		}

		if(!preg_match('/^.[' . Globals::$repertoires . ']+k?$/', $mask)){
			$msg = sprintf('parse_template: a mask may contain only the letters "%s".',
				implode('", "', array_keys(Globals::$alphabets)));
			return 0;
		}

		# Check prefix for errors.
		$has_cc = substr($mask, -1) === 'k';
		if($has_cc){
			$repertoire = self::getAlphabet($template);
			if(empty($repertoire)){
				$msg = sprintf('parse_template: the check character cannot be determined.');
				return 0;
			}

			if($repertoire !== TRUE){
				$alphabet = Globals::$alphabets[$repertoire];
				foreach(str_split($prefix) as $c){
					// strlen() avoid an issue with str_split() when there is no prefix.
					if(strlen($c) && $c !== '/' && strpos($alphabet, $c) === FALSE){
						// By construction, only "[de]+" templates can set an
						// error here.
						$msg = sprintf('parse_template: with a check character at the end, a mask of type "[de]+" may contain only characters from "%s".',
							Globals::$alphabets['e']);
						return 0;
					}
				}
			}
		}

		# If we get here, the mask is well-formed.  Now try to come up with
		# a short synonym for the template; it should start with the
		# template's prefix and then an integer representing the number of
		# letters in identifiers generated by the template.  For example,
		# a template of "ft.rddeek" would be "ft5".
		#
		$masklen = strlen($mask) - 1;    # subtract one for [rsz]
		$msg = $prefix . $masklen;
		if(substr($mask, 0, 1) === 'z'){           # "+" indicates length can grow
			$msg .= '+';
		}

		# r means random;
		# s means sequential, limited;
		# z means sequential, no limit, and repeat most significant mask
		#   char as needed;

		$total = 1;
		foreach(str_split($mask) as $c){
			// Avoid to str_split() an empty mask.
			if(strlen($c) == 0){
				break;
			}
			# Mask chars it could be are: repertoires or k
			if(isset(Globals::$alphabets[$c])){
				$total *= strlen(Globals::$alphabets[$c]);
			}
			else if(preg_match('/[krsz]/', $c)){
				continue;
			}
		}

		$gen_type = substr($mask, 0, 1) === 'r' ? 'random' : 'sequential';
		# $message was set to the synonym already
		return substr($mask, 0, 1) === 'z' ? Globals::NOLIMIT : $total;
	}

	/**
	 * Returns the status, the output and the errors of an external command.
	 *
	 * @param string $cmd
	 * @param int    $status
	 * @param string $output
	 * @param string $errors
	 *
	 * @return void
	 * @throws Exception
	 */
	static public function executeCommand($cmd, &$status, &$output, &$errors)
	{
		// Using proc_open() instead of exec() avoids an issue: current working
		// directory cannot be set properly via exec().  Note that exec() works
		// fine when executing in the web environment but fails in CLI.
		$descriptorSpec = array(
			0 => array('pipe', 'r'), //STDIN
			1 => array('pipe', 'w'), //STDOUT
			2 => array('pipe', 'w'), //STDERR
		);
		if($proc = proc_open($cmd, $descriptorSpec, $pipes, getcwd())){
			$output = stream_get_contents($pipes[1]);
			$errors = stream_get_contents($pipes[2]);
			foreach($pipes as $pipe){
				fclose($pipe);
			}
			$status = proc_close($proc);
		}
		else{
			throw new Exception("Failed to execute command: $cmd.");
		}
	}
}
