<?php

include "lib/noid/Noid.php";
require_once('lib/resolver/URLResolver.php');
require_once "NoidUI.php";


$resolver = new mattwright\URLResolver();
print $resolver->resolveURL('http://192.168.1.16/ark:/61220/utsc42')->getURL();
