<?php

include "lib/noid/Noid.php";
require_once('lib/resolver/URLResolver.php');
require_once "NoidUI.php";


$resolver = new mattwright\URLResolver();
print $resolver->resolveURL('http://192.168.1.16/ark:/61220/utsc14')->getURL();
print $resolver->resolveURL('http://goo.gl/0GMP1')->getURL();


$resolver = new mattwright\URLResolver();

# Identify your crawler (otherwise the default will be used)
$resolver->setUserAgent('Mozilla/5.0 (compatible; YourAppName/1.0; +http://www.example.com)');

# Designate a temporary file that will store cookies during the session.
# Some web sites test the browser for cookie support, so this enhances results.
$resolver->setCookieJar('/tmp/url_resolver.cookies');

# resolveURL() returns an object that allows for additional information.
$url = 'http://goo.gl/0GMP1';
$url_result = $resolver->resolveURL($url);

# Test to see if any error occurred while resolving the URL:
if ($url_result->didErrorOccur()) {
    print "there was an error resolving $url:\n  ";
    print $url_result->getErrorMessageString();
}

# Otherwise, print out the resolved URL.  The [HTTP status code] will tell you
# additional information about the success/failure. For instance, if the
# link resulted in a 404 Not Found error, it would print '404: http://...'
# The successful status code is 200.
else {
    print $url_result->getHTTPStatusCode();
    print ': ';
    print $url_result->getURL();
}