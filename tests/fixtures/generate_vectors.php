<?php
/**
 * Generates golden conformance vectors from the LEGACY Noid4Php implementation.
 *
 * The Python port in `minting/noid.py` must reproduce these exactly — that is what
 * guarantees newly minted ARKs are indistinguishable from the ~100k already in
 * production, and that legacy IDs still pass check-character validation.
 *
 * Usage (from the repo root, with the legacy checkout alongside):
 *
 *     php tests/fixtures/generate_vectors.php > tests/fixtures/noid_vectors.json
 *
 * Override the legacy location with NOIDLIB=/path/to/admin/NoidLib.
 *
 * The legacy application is github.com/digitalutsc/arks-service-archived (the
 * name digitalutsc/arks-service now belongs to the Django rewrite). CI checks it
 * out pinned to b30909c, the commit these vectors were generated from.
 */

$default = __DIR__ . '/../../../legacy/application/arks-service/admin/NoidLib';
$LIB = getenv('NOIDLIB') ?: $default;
if (!is_dir($LIB)) {
    fwrite(STDERR, "Legacy NoidLib not found at: $LIB\n");
    exit(1);
}

// Helper.php does `require_once 'Globals.php'` relative to the include path.
set_include_path($LIB . '/lib' . PATH_SEPARATOR . get_include_path());

require_once $LIB . '/lib/Globals.php';
require_once $LIB . '/lib/Helper.php';
require_once $LIB . '/custom/GeneratorArk.php';

use Noid\Lib\Globals;
use Noid\Lib\Helper;
use Noid\Lib\Custom\GeneratorArk;

$out = [
    'source' => 'legacy Noid4Php (digitalutsc/arks-service admin/NoidLib)',
    'php_version' => PHP_VERSION,
    'alphabets' => Globals::$alphabets,
    'alphabet_checks' => Globals::$alphabetChecks,
    'repertoires' => Globals::$repertoires,
];

// --- n2xdig ---------------------------------------------------------------
$masks = [
    'zd', 'zeee', 'zededede', 'zdeek',
    'rddd', 'rdddd', 'reee', 'rdedeedd', 'rdedk', 'redek', 'reedeedk',
    'sdddddd', 'sdd', 'se', 'sdede', 'sdeeedk',
    'zl', 'zv', 'rww', 'sxx', 'zi', 'rEE',
];
$nums = array_merge(
    range(0, 40),
    [64, 99, 100, 101, 255, 728, 840, 999, 1000, 1001, 1728, 12345, 24389,
     99999, 100000, 823543, 1000000, 12345678, 70728099]
);
$n2xdig = [];
foreach ($masks as $mask) {
    foreach ($nums as $num) {
        $n2xdig[] = ['num' => $num, 'mask' => $mask, 'expected' => GeneratorArk::n2xdig($num, $mask)];
    }
}
// Malformed masks must return '' (not throw).
foreach (['', 'd', 'xyz', 'rkd', 'zdk k', 'qdd', 'r', 'z'] as $mask) {
    $n2xdig[] = ['num' => 5, 'mask' => $mask, 'expected' => GeneratorArk::n2xdig(5, $mask)];
}
$out['n2xdig'] = $n2xdig;

// --- checkChar ------------------------------------------------------------
// Real usage: the check char is computed over the FULL id, including the
// firstpart (NAAN + '/' + prefix). A trailing '+' means "compute it".
$check_ids = [
    ['61220/utsc1+', 'e'], ['61220/utsc123+', 'e'], ['61220/utsc0+', 'e'],
    ['61220/f5bc12+', 'e'], ['12345/xy9999+', 'e'], ['61220/1+', 'e'],
    ['+', 'e'], ['b+', 'e'], ['0+', 'e'], ['zzzz+', 'e'],
    ['61220/utsc1+', 'd'], ['61220/utsc1+', 'x'], ['61220/utsc1+', 'v'],
    ['61220/utsc1+', 'l'], ['61220/utsc1+', 'w'], ['61220/utsc1+', 'i'],
    ['13030/xf93gt2+', 'e'], ['13030/xf93gt2q', 'e'],
    // Verification (no '+'): correct char returns the id, wrong char returns null.
    ['61220/utsc1b', 'e'], ['61220/utsc1z', 'e'], ['61220/utsc1c', 'e'],
    ['61220/utsc1d', 'e'], ['61220/utsc1x', 'e'],
];
$check = [];
foreach ($check_ids as [$id, $alpha]) {
    $check[] = ['id' => $id, 'alphabet' => $alpha, 'expected' => Helper::checkChar($id, $alpha)];
}
// Empty / unknown alphabet handling.
$check[] = ['id' => '', 'alphabet' => 'e', 'expected' => Helper::checkChar('', 'e')];
$check[] = ['id' => 'abc+', 'alphabet' => 'Q', 'expected' => Helper::checkChar('abc+', 'Q')];
$out['check_char'] = $check;

// --- parseTemplate --------------------------------------------------------
$templates = [
    // Documented in the legacy admin UI.
    '.rddd', '.sdddddd', '.zd', 'bc.rdddd', '8rf.sdd', '.se', 'h9.reee', '.zeee',
    '.rdedeedd', '.zededede', 'sdd.sdede', '.rdedk', '.sdeeedk', '.zdeek',
    '63q.redek', 'f5.reedeedk',
    // Prefix + template as `dbcreate` concatenates them.
    'utsc.zd', 'utsc.zeee', 'utsc.sdddddd', 'dsu.rdddd',
    // Other repertoires.
    '.zl', '.zv', '.rww', '.sxx', '.zi', '.rEE', '.zc',
    // Error cases.
    '', '-', 'noperiod', '.qxyz', '.dddd', '.rdkd', '.rkk', 'x.', '.r',
    // Check-char repertoire resolution edge cases.
    'bc.rdddk', 'a.zdk', 'l.zdk', 'e.zdk', '.zwk', '.zvk',
];
$parse = [];
foreach ($templates as $t) {
    $prefix = $mask = $gen_type = $message = null;
    $total = Helper::parseTemplate($t, $prefix, $mask, $gen_type, $message);
    $parse[] = [
        'template' => $t,
        'total' => $total,
        'prefix' => $prefix,
        'mask' => $mask,
        'gen_type' => $gen_type,
        'message' => $message,
    ];
}
$out['parse_template'] = $parse;

// --- getAlphabet ----------------------------------------------------------
$alpha = [];
foreach ($templates as $t) {
    $r = Helper::getAlphabet($t);
    $alpha[] = ['template' => $t, 'expected' => $r];
}
$out['get_alphabet'] = $alpha;

// --- End-to-end: sequential minting, the production case -------------------
// Mirrors mint(): id = firstpart . n2xdig(counter, mask), then check char.
$sequences = [];
foreach ([['61220/utsc', 'zd'], ['61220/utsc', 'zeee'], ['61220/', 'sdddddd'],
          ['61220/f5', 'reedeedk'], ['61220/63q', 'redek']] as [$firstpart, $mask]) {
    $ids = [];
    foreach (array_merge(range(0, 30), [99, 100, 999, 1000, 99999, 100000]) as $n) {
        $id = $firstpart . GeneratorArk::n2xdig($n, $mask);
        if (substr($mask, -1) === 'k') {
            $repertoire = preg_match('/^.[de]+k$/', $mask) ? 'e' : 'e';
            $id = Helper::checkChar($id, $repertoire);
        }
        $ids[] = ['n' => $n, 'id' => $id];
    }
    $sequences[] = ['firstpart' => $firstpart, 'mask' => $mask, 'ids' => $ids];
}
$out['sequences'] = $sequences;

echo json_encode($out, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), "\n";
