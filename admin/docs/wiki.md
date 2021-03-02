## What is Ark Identifiers ?

https://wiki.lyrasis.org/display/ARKs/ARK+Identifiers+FAQ

## Base Projects:

https://github.com/Daniel-KM/Noid4Php  
https://github.com/AkioUnity/Noid4Php

## DSU Implementation of ARKs

### Github Repo:

  - https://github.com/digitalutsc/ark-services

-----

## Deployment:

### In Drupal VM:

  - Download VM from: https://github.com/geerlingguy/drupal-vm.
  - Open terminal, and change to the drupal-vm directory cd
    DIR/drupal-vm and run `vagrant up` to have VM running.
  - Remote access to VM by running `vagrant ssh`
  - Change directory by run cd `/var/www`, then donwload the source code
    by running git clone https://github.com/digitalutsc/ark-services.git
  - Enable hosting for the Ark Service by running sudo nano
    /etc/apache2/sites-available/vhosts.conf, then paste the following
    code to the file:

<!-- end list -->

```
<VirtualHost *:80>
  ServerName ark.drupalvm.test
  ServerAlias www.ark.drupalvm.test
  DocumentRoot "/var/www/ark-services"

    <Directory "/var/www/ark-services">
        AllowOverride All
        Options -Indexes +FollowSymLinks
        Require all granted
    </Directory>
    <FilesMatch \.php$>
    SetHandler "proxy:fcgi://127.0.0.1:9000"
    </FilesMatch>

</VirtualHost>    

```

  - Reload Apache by running `sudo systemctl reload apache2`
  - Open another terminal window, run `sudo nano /etc/hosts`, then add `192.168.88.88 ark.drupalvm.test` at the end of the file and save it.
  - To create the database, visit http://adminer.drupalvm.test/index.php.
  - Login with the below info to login to manage MYSQL.

```
System: MYSQL
Server: locahost
Username: root  
Password:root   
Database: Leave empty   
```

  - After logging successfully to Adminer, create a database for the Ark Identifiers.
  - In terminal, running `sudo nano /var/www/ark-services/config/MysqlArkConf.php`, and paste the below code, and set the name of the database which has been created above to $mysql_dbname, then save it.
```php
<?php

namespace Noid\Lib\Custom;

class MysqlArkConf
{
    static public $mysql_host = 'localhost';
    static public $mysql_user = 'root';
    static public $mysql_passwd = 'root';
    static public $mysql_dbname = ''; // please enter the name of database which you have just created.  
    static public $mysql_port = 3306;
    static public $path_db_backup = "/var/www/ark-services/db/backup/";

}
```

  - Change the permission of the directory db by running `sudo chmod 777 /var/www/ark-services/admin/db`
  - Go to http://ark.drupalvm.test and fill out the form in screenshot as below for initially set the system up.
  - Visit the http://ark.drupalvm.test/admin/admin.php and login with the account which has been created in the previous step to get started.

-----

### In an Apache server (for production's deployment)
1. Follow [this guide](https://www.digitalocean.com/community/tutorials/how-to-install-linux-apache-mysql-php-lamp-stack-on-ubuntu-20-04) to install the LAMP stack to your server. **Please note:**
    * In **STEP 4**, follow exactly this step with **ark-services** instead of **your_domain**
    * Then, open the terminal, change the current directory by running `cd /var/www`,
    * then download the source code by running `git clone https://github.com/digitalutsc/ark-services.git` 
2. Follow [this guide](https://www.digitalocean.com/community/tutorials/how-to-install-and-secure-phpmyadmin-on-ubuntu-20-04) to install phpMyAdmin to your server.
3. Using phpMyAdmin to create an user, a database and then assign that user to the database with the following Privileges as screenshot below:
   
 ![](https://github.com/digitalutsc/ark-services/blob/master/admin/docs/images/Screen%20Shot%202020-10-22%20at%2012.42.35%20PM.png?raw=true)
   

4. In terminal, running `sudo nano /var/www/ark-services/config/MysqlArkConf.php`, and paste the following code, and set the name of variables by which you created in the previous step, then save it.

````php
<?php

namespace Noid\Lib\Custom;

class MysqlArkConf
{
    static public $mysql_host = ''; // host of your server
    static public $mysql_user = ''; // your MYSQL username
    static public $mysql_passwd = ''; // your MYSQL password
    static public $mysql_dbname = ''; // please enter the name of database which you have just created.  
    static public $mysql_port = 3306;
    static public $path_db_backup = "/var/www/ark-services/db/backup/"; // backup directory for database snapshot
    
}

````

-----

### Installation

  - After place the code in the server, please visit:
    https://yoursite (for the first time, it will redirect to
    https://yoursite/admin/install.php). 
  - Fill out Organization information. 
  - Enter System Administrator login credentials (Password will be
    encrypted and saved in MYSQL database).

![](https://github.com/digitalutsc/ark-services/blob/master/admin/docs/images/Screen%20Shot%202021-03-01%20at%208.26.06%20PM.png?raw=true)

-----

### To Reset and Install again

  - Access to Ark database in PHPMyAdmin, and drop only two table
    **“system”** and **“user”**, then refresh page
    https://yoursite/admin/admin.php, the installation step above
    will be repeated.
      - **<span class="underline">Note</span>**: the minted Ark IDs
        won’t be effected

-----

# Usage

## Create a collection of Ark IDs

  - Visit: https://yoursite/admin/admin.php 
  - Fill out the “Create Database” form, then click Create. 
      - <span class="underline">**Note:**</span>  To
        ensure the sufficient of the Ark ID lookup for redirection, the
        prefix must be unique (already enforced) among multiple
        databases.

![Create a collection of Ark IDs](https://github.com/digitalutsc/ark-services/blob/master/admin/docs/images/Screen%20Shot%202020-10-22%20at%203.12.29%20PM.png?raw=true)

## Select a Template:

  - **.rddd**: to mint random 3-digit numbers, stopping after 1000th
  - **.sdddddd**: to mint sequential 6-digit numbers, stopping after
    millionth
  - **.zd**: sequential numbers without limit, adding new digits as
    needed
  - **bc.rdddd**: random 4-digit numbers with constant prefix bc
  - **8rf.sdd**: sequential 2-digit numbers with constant prefix 8rf
  - **.se**: sequential extended-digits (from
    0123456789bcdfghjkmnpqrstvwxz)
  - **h9.reee**: random 3-extended-digit numbers with constant prefix h9
  - **.zeee**: unlimited sequential numbers with at least 3
    extended-digits
  - **.rdedeedd** : random 7-char numbers, extended-digits at chars 2,
    4, and 5
  - **.zededede**: unlimited mixed digits, adding new extended-digits as
    needed
  - **sdd.sdede** : sequential 4-mixed-digit numbers with constant
    prefix sdd
  - **.rdedk** : random 3 mixed digits plus final (4th) computed check
    character
  - **.sdeeedk** : 5 sequential mixed digits plus final extended-digit
    check char
  - **.zdeek** : sequential digits plus check char, new digits added as
    needed
  - **63q.redek** : prefix plus random 4 mixed digits, one of them a
    check char

## Ark URL structure:

https://wiki.lyrasis.org/display/ARKs/ARK+Identifiers+FAQ

-----

## Delete a collection of Arks

1.  Go in phpMyadmin, then database name which was set at
    <span class="underline">**$mysql\_dbname**</span> above
2.  Drop the table which enter in the previous step.
3.  Back to https://yoursite/admin/admin.php, refresh the page
      - <span class="underline">**Note:**</span>
        <span style="background:yellow;">Please avoid remove the system
        and user tables, otherwise, the current configuration will be
        lost, the installation step will be repeated</span>.

-----

## Minting

![minting](https://github.com/digitalutsc/ark-services/blob/master/admin/docs/images/Screen%20Shot%202020-10-19%20at%209.15.44%20AM.png?raw=true)

-----

## Binding an Ark ID

  - **Click the “Binding” button on top of the Established Ark IDs
    Table**

![binding-step1](https://github.com/digitalutsc/ark-services/blob/master/admin/docs/images/Screen%20Shot%202021-03-01%20at%209.11.53%20AM.png?raw=true)  |  ![binding-step2](https://github.com/digitalutsc/ark-services/blob/master/admin/docs/images/Screen%20Shot%202021-03-01%20at%209.13.40%20AM.png?raw=true)
:-------------------------:|:-------------------------:

-----

## Unbinding Ark ID

  - **Click the “Unbinding” button on top of the Established Ark IDs
    Table**

![unbinding-step1](https://github.com/digitalutsc/ark-services/blob/master/admin/docs/images/Screen%20Shot%202021-03-01%20at%209.17.53%20AM.png?raw=true)  |  ![unbinding-step2](https://github.com/digitalutsc/ark-services/blob/master/admin/docs/images/Screen%20Shot%202021-03-01%20at%209.18.03%20AM.png?raw=true)
:-------------------------:|:-------------------------:

## **Bulk Bind**

**Workflow:**

1.  Mint Ark ID(s)
2.  Download template.csv(https://yoursite/admin/template.csv),
    place the above minted Ark IDs into the ARK_ID column.
3.  There no limitation of data field(s) to be bound with an Ark ID.
    **For UTSC only, highly recommend to have the below essential
    columns which are already included in the template CSVs above and
    add more column(s) if needed for other metadata**.
    1.  Ark_ID: MANDATORY for binding.
    2.  URL: MANDATORY will be redirected to after Ark ID’s URL Resolver.
    3.  LOCAL\_ID: Object’s unique ID in the repository.
    4.  PID: persistent Identifiers
    5.  COLLECTION (Optional): to assist on searching in the table.
4.  Upload the CSV to start the process.



![](https://github.com/digitalutsc/ark-services/blob/master/admin/docs/images/Screen%20Shot%202021-03-01%20at%209.05.10%20AM.png?raw=true)  |  ![bulkbind-step2](https://github.com/digitalutsc/ark-services/blob/master/admin/docs/images/Screen%20Shot%202021-03-01%20at%209.08.20%20AM.png)
:-------------------------:|:-------------------------:

-----

## Generate reports

![](https://github.com/digitalutsc/ark-services/blob/master/admin/docs/images/Screen%20Shot%202021-03-01%20at%208.45.54%20AM.png?raw=true)

-----

# Rest API

Structure: https://yoursite/admin/rest.php?db=DB_NAME&op=OP_NAME (optional: \&ark\_ID={{Ark ID}})

Example:  
* GET all minted Ark IDs: https://yoursite/admin/rest.php?db=dsu_ark&op=minted
* GET all fields bound to an Ark ID https://yoursite/admin/rest.php?db=dsu_ark&ark_id=61220/utsc1&op=fields
* GET Prefix of a collection: https://yoursite/admin/rest.php?db=dsu_ark&ark_id=61220/utsc1&op=firstpart
* GET all bound Ark objects: https://yoursite/admin/rest.php?db=dsu_ark&ark_id=61220/utsc1&op=bound
* GET PID of an Ark object: https://yoursite/admin/rest.php?db=dsu_ark&ark_id=61220/utsc1&op=pid
* GET MODS Url: https://yoursite/admin/rest.php?db=dsu_ark&ark_id=61220/utsc10&op=url
* GET NAA of a collection: https://yoursite/admin/rest.php?db=dsu_ark&ark_id=61220/utsc10&op=naa
* GET basic info of a collection: https://yoursite/admin/rest.php?db=dsu_ark&ark_id=61220/utsc10&op=dbinfo
* POST for Bulk Bind:

```javascript
$.post("https://yoursite/admin/rest.php?db=DB_NAME&op=bulkbind&stage=upload", {data: pdata, security: password})
.done(function (data) {
    var result =  JSON.parse(data);
    if (result.success == 401) {
          // add a UI handle when REST return unauthorized (code:401), it happens when System Admin's password above are not matched
    }
    else {
        // add a UI handle when REST return success (code: 1)
    }

})
.fail(function () {
    // add a UI handle when POST request failed
});
```

-----

# Resolver

**Workflow:**

* **Step 1**. Catch coming traffic and detect Ark URL. In **.htaccess** at
the root directory, obtain Ark ID information and redirect to
resolver.php:

```
RewriteEngine On
RewriteCond %{REQUEST_URI}  ^/ark:/.*$
#RewriteRule ^(.*)$ /ark-services/$1 [L]
RewriteRule ^(.*)$ /resolver.php?q=$1 [L]
```

* **Step 2**. Captured Ark ID from URL. ie.
https://yoursite/ark:/61220/utsc6 (which is 61220/utsc6)  
* **Step 3**, Get prefix (‘utsc’ from example above), from this prefix,
identify which database to lookup the object bound to this ARK ID (This
is why the prefix need to be unique)  
* **Step 4**. Look for field URL first, if URL is valid, redirect to that
URL  
* **Step 5**. If field URL is not available, use PID instead, establishing
the URL by combine **https + NAA + PID** (coded exclusively for UTSC-DSU
usage)

Code can be found at **resolver.php**: (https://github.com/digitalutsc/ark-services/blob/master/resolver.php)

-----

# Maintenance

## Database backup

Each time of mining, (bulk) binding ARK ID (s), the system will
automatically take a snapshot of the database and store it under the
directory
*<span class="underline">/var/www/dsu-noid4php/db/backup</span>* which
can be preset or changed to the **$path\_db\_backup** in
MyslqArkConf.php file:

```php
    <?php
    
    class MysqlArkConf{
        static public $mysql_host = '';
        static public $mysql_user = '';
        static public $mysql_passwd = '';
        static public $mysql_dbname = '';
        static public $mysql_port = 3306;
        static public $path_db_backup = "/var/www/dsu-noid4php/admin/db/backup/";
    }
```

