<?php
require_once 'NoidLib/custom/Database.php';
require_once 'NoidLib/custom/MysqlArkConf.php';
use Noid\Lib\Custom\MysqlArkConf;
use Noid\Lib\Custom\Database;

$reCAPTCHA_sitekey = Database::getReCAPTCHA_sitekey()['_value'];

?>

<script type="text/javascript">
    var verifyCallback = function(response) {
        console.log(response);
        if (response !== 'undefined') {
            $('#submit_btn_8').prop('disabled', false);
        }
    };
    var onloadCallback = function() {
        grecaptcha.render('grecaptcha', {
            'sitekey' : '<?php print $reCAPTCHA_sitekey; ?>',
            'callback' : verifyCallback,
            'theme' : 'light'
        });
    };

</script>

<form id="contact_form" pix-confirm="hidden_pix_8">
    <div id="result"></div>
    <input type="text" name="name" id="name" placeholder="Enter Your Full Name"
           class="pix_text">
    <input type="email" name="email" id="email" placeholder="Enter Your Email"
           class="pix_text">
    <textarea type="text" name="body" id="body" placeholder="Please tell us more detail about the Ark IDs which you would like to create." resize="true"
              class="pix_text"></textarea>
    <div id="grecaptcha"></div>
    <button class="subscribe_btn pix_text" id="submit_btn_8" disabled>
        <span class="editContent" style="">SEND REQUEST</span>
    </button>
</form>
<script src="https://www.google.com/recaptcha/api.js?onload=onloadCallback&render=explicit"
        async defer>
</script>
