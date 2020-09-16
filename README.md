# dsu_noid4php 
This repo is customized version of the original Noid4Php (https://github.com/Daniel-KM/Noid4Php)

Note: 
+ Clone this repo to the root of your localhost (ie. /var/www/....)
+ Open web browswer and visit http://{{ localhost }}/dsu_noid4php
+ Create an directory named "db" and change the owner to www-data:
    + cd  dsu_noid4php
    + mkdir db 
    + sudo chown -Rf www-data:www-data db 
+ Open /var/www/dsu_noid4php/.htaccess and find "RewriteRule ^(.*)$ http://192.168.1.16/dsu_noid4php/$1 [L]", change 192.168.1.16 to your domain name 
+ If you set this repo as the root of your server or localhost, create/open .htaccess at the root diirectory (ie. /var/www/.htaccess)

RewriteEngine On
RewriteCond %{REQUEST_URI}  ^/ark:/.*$
RewriteRule ^(.*)$ http://192.168.1.16/dsu_noid4php/$1 [L] #change 192.168.1.16 to your domain name 
