<?php
use PHPMailer\PHPMailer\PHPMailer;
use PHPMailer\PHPMailer\Exception;
error_reporting(E_ALL);
ini_set("log_errors", 1);
ini_set("error_log", dirname(__FILE__) . "/php-error.log");

if($_POST)
{
	$language = "EN";
	include("config.php");
	include("messages.php");
	//-----------------------------------------------------------------------------------------
	$use_reCaptcha = false;
	if($secret != ""){
		$use_reCaptcha = true;
	}

	/* Install headers */
	header('Expires: 0');
	header('Cache-Control: no-cache, must-revalidate, post-check=0, pre-check=0');
	header('Pragma: no-cache');
	header('Content-Type: application/json; charset=utf-8');

	if($use_reCaptcha){
		// empty response
		$response = null;
		// grab recaptcha library
		require_once "recaptchalib.php";
		// check secret key
		$reCaptcha = new ReCaptcha($secret);
	}


	//check if its an ajax request, exit if not
	if(!isset($_SERVER['HTTP_X_REQUESTED_WITH']) AND strtolower($_SERVER['HTTP_X_REQUESTED_WITH']) != 'xmlhttprequest') {
		//exit script outputting json data
		$output = json_encode(
		array(
			'type'=>'error',
			'text' => 'Request must come from Ajax'
		));
		die($output);
	}

	$values = array($_POST);
	$o_string = "";
	$o_string1 = "";
	$o_string_html = "";
	$user_Email = $to_Email;
	$pix_extra = array();
	$has_type = false;
	$the_type = "";
	$the_list = "";
	foreach ($values as  $value) {
		foreach ($value as $variable => $v) {
			if(filter_var($variable, FILTER_SANITIZE_STRING) == 'pixfort_form_type'){
				if(filter_var($variable, FILTER_SANITIZE_STRING) != ''){
					$the_type = $v;
					$has_type =true;
				}
			}elseif(filter_var($variable, FILTER_SANITIZE_STRING) == 'pixfort_form_list'){
				if(filter_var($variable, FILTER_SANITIZE_STRING) != ''){
					$the_list = $v;
				}
			}elseif(filter_var($variable, FILTER_SANITIZE_STRING) == 'g-recaptcha-response'){
				if($use_reCaptcha){
					$response = $reCaptcha->verifyResponse(
						$_SERVER["REMOTE_ADDR"],
						$v
					);
					if ($response == null || (!$response->success)) {
						$output = json_encode(array('type'=>'error', 'text' => $lang[$language]['captcha']));
						die($output);
					}
				}
			}elseif(filter_var($variable, FILTER_SANITIZE_STRING) == 'g_recaptcha_response'){
                if($use_reCaptcha){
                    $response = $reCaptcha->verifyResponse(
                        $_SERVER["REMOTE_ADDR"],
                        $v
                    );
                    if ($response == null || (!$response->success)) {
                        $output = json_encode(array('type'=>'error', 'text' => $lang[$language]['captcha']));
                        die($output);
                    }
                }
            }else{
				$o_string1 .= filter_var($variable, FILTER_SANITIZE_STRING) . ': '. filter_var($v, FILTER_SANITIZE_STRING) ." -  \n";
				$o_string .= "<b>".filter_var($variable, FILTER_SANITIZE_STRING) . '</b>: '. filter_var($v, FILTER_SANITIZE_STRING) ." -  <br>";
				if(strtolower(filter_var($variable, FILTER_SANITIZE_STRING)) == 'email'){
					$user_Email = $v;
					if(!validMail($user_Email)) //email validation
					{
						$output = json_encode(array('type'=>'error', 'text' => $lang[$language]['check_email']));
						die($output);
					}
				}else{
					$pix_extra[filter_var($variable, FILTER_SANITIZE_STRING)] = filter_var($v, FILTER_SANITIZE_STRING);
				}
			}
		}
	}

	$form_type = $mail_type;
	if($has_type){
		$form_type = $the_type;
	}

	if($form_type == 'ce'){
		pixmail($o_string, $user_Email, $to_Email, $subject, $language, $lang);
	}elseif($form_type == 'smtp'){
		pixsmtp($o_string, $user_Email, $to_Email, $subject, $language, $lang);
	}elseif($form_type == 'mc'){
		sendMailChimp($user_Email, $the_list, $pix_extra, $language, $lang);
	}elseif($form_type == 'cm'){
		sendCampaign($user_Email, $the_list, $pix_extra, $language, $lang);
	}elseif($form_type == 'gr'){
		sendGetResponse($user_Email, $the_list, $pix_extra, $language, $lang);
	}elseif($form_type == 'aw'){
		sendAWeber($user_Email, $the_list, $pix_extra, $language, $lang);
	}elseif($form_type == 'ac'){
		sendActiveCampaign($user_Email, $the_list, $pix_extra, $language, $lang);
	}elseif($form_type == 'ml'){
		sendMailerLite($user_Email, $the_list, $pix_extra, $language, $lang);
	}elseif($form_type == 'fm'){
		sendFreshMail($user_Email, $the_list, $pix_extra, $language, $lang);
	}elseif($form_type == 'sl'){
		sendSendloop($user_Email, $the_list, $pix_extra, $language, $lang);
	}elseif($form_type == 'mw'){
		sendMailWizz($user_Email, $the_list, $pix_extra, $language, $lang);
	}elseif($form_type == 'sendy'){
		sendSendy($user_Email, $the_list, $pix_extra, $language, $lang);
	}elseif($form_type == 'hs'){
		sendHubspot($user_Email, $the_list, $pix_extra, $language, $lang);
	}elseif($form_type == 'ic'){
		sendiContact($user_Email, $the_list, $pix_extra, $language, $lang);
	}else{
		$output = json_encode(array('type'=>'error', 'text' => 'Error: Wrong mail_type attribute!'));
		if($has_type){
			$output = json_encode(array('type'=>'error', 'text' => 'Error: Wrong pix-form-type attribute provided for the form!'));
		}
		die($output);
	}

} // End POST

	function pixmail($o_string, $user_Email, $to_Email, $subject, $language, $lang)
	{
		$final_msg = "\n"."A new subscription,<br>"."\n";
		$final_msg .= $o_string;

		$to_Email = str_replace(' ', '', $to_Email);
		$email_array = explode(',', $to_Email);
		$sentMail = false;
		foreach ($email_array as $email) {
		    //proceed with PHP email.
			$headers = 'From: '.$email.'' . "\r\n" .
			'Reply-To: '.$user_Email.'' . "\r\n" .
			'X-Mailer: PHP/' . phpversion().'' . "\r\n" .
			"Content-Type: text/html;charset=utf-8";
			// send mail
			$sentMail = @mail($email, $subject, $final_msg, $headers);
			if(!$sentMail){
				$sentMail = @mail($email, $subject, $final_msg, '');
			}
		}

		$output = json_encode(array('type'=>'message', 'text' => $lang[$language]['success']));
			die($output);
		if(!$sentMail){
			$output = json_encode(array('type'=>'error', 'text' => $lang[$language]['php_error']));
			die($output);
		}else{
			$output = json_encode(array('type'=>'message', 'text' => $lang[$language]['success']));
			die($output);
		}
	}

	function pixsmtp($o_string_html, $user_Email, $to_Email, $subject, $language, $lang){
		if(defined('SMTP_HOST') && defined('SMTP_USER') && defined('SMTP_PASS')){
			// require 'phpmailer/PHPMailerAutoload.php';

			require 'phpmailer/Exception.php';
			require 'phpmailer/PHPMailer.php';
			require 'phpmailer/SMTP.php';

			$mail = new PHPMailer;

			$final_msg = "\n"."A new Subscribe,"."<br>";
			$final_msg .= $o_string_html;

			// $mail->SMTPDebug = 3;                               // Enable verbose debug output

			$mail->isSMTP();                                      // Set mailer to use SMTP
			$mail->Host = SMTP_HOST;  // Specify main and backup SMTP servers (e.g. smtp.gmail.com)
			$mail->SMTPAuth = true;                               // Enable SMTP authentication
			$mail->Username = SMTP_USER;                 // SMTP username
			$mail->Password = SMTP_PASS;                           // SMTP password
			$mail->SMTPSecure = 'ssl';                            // Enable TLS encryption, `ssl` also accepted
			$mail->Port = 465;                                    // TCP port to connect to
            $mail->CharSet = 'UTF-8';


            $to_Email = str_replace(' ', '', $to_Email);
			$email_array = explode(',', $to_Email);
			$sentMail = false;

			$mail->setFrom($email_array[0], getName($email_array[0]));
			foreach ($email_array as $email){
				$mail->addAddress($email);     // Add a recipient
			}
			//$mail->addAddress('');               // Name is optional
			$mail->addReplyTo($user_Email, 'RE Subscription');
			//$mail->addCC('cc@example.com');
			//$mail->addBCC('bcc@example.com');

			//$mail->addAttachment('attachments/book.png');         // Add attachments
			//$mail->addAttachment('/tmp/image.jpg', 'new.jpg');    // Optional name
			$mail->isHTML(true);                                  // Set email format to HTML
			$mail->Subject = $subject;
			$mail->Body    = $final_msg;
			$mail->AltBody = $final_msg;

			if(!$mail->send()) {
			    $output = json_encode(array('type'=>'error', 'text' => 'Mailer Error: ' . $mail->ErrorInfo));
				die($output);
			} else {
			    $output = json_encode(array('type'=>'message', 'text' => $lang[$language]['success']));
				die($output);
			}
		}else{
			$output = json_encode(array('type'=>'error', 'text' => 'Error: check SMTP configuration in config.php file.'));
			die($output);
		}
	}

	function validMail($email){
		if(filter_var($email, FILTER_VALIDATE_EMAIL)){
			return true;
		} else {
			return false;
		}
	}

	function sendMailChimp($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){
		if(defined('MC_APIKEY') && defined('MC_LISTID')){
			include('api_mailchimp/MailChimp.php');
			$MailChimp = new MailChimp(MC_APIKEY);
			$list_id = MC_LISTID;
			if($merge_vars && isset($merge_vars)){
				$ff = array(
	                'email_address' => $mailSubscribe,
	                'status'        => 'subscribed',
	                'merge_fields'  => $merge_vars
	            );
			}else{
				$ff = array(
	                'email_address' => $mailSubscribe,
	                'status'        => 'subscribed'
	            );
			}

            $hash = md5($mailSubscribe);
			$result = $MailChimp->put("lists/$list_id/members/$hash",$ff);

            if ($MailChimp->success()) {
			    $output = json_encode(array('type'=>'message', 'text' => $lang[$language]['subscription']));
			    die($output);
			} else {
				$resp = $MailChimp->getLastResponse();
			    if($resp['headers']['http_code']==400){
			    	//$output = json_encode(array('type'=>'error', 'text' => $lang[$language]['email_exists']));
			    	$output = json_encode(array('type'=>'error', 'text' => $MailChimp->getLastError()));
			    }else{
			    	$output = json_encode(array('type'=>'error', 'text' => $MailChimp->getLastError()));
			    }
				die($output);
			}
		}else{
			$output = json_encode(array('type'=>'error', 'text' => 'Error: make sure that the API key and the list id are properly configured.'));
			die($output);
		}
	}
	function sendMailChimp2($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){
		if(defined('MC_APIKEY') && defined('MC_LISTID')){
			$api = new MCAPI(MC_APIKEY);
			if($api->listSubscribe(MC_LISTID, $mailSubscribe, $merge_vars) !== true){
				if($api->errorCode == 214){
					$output = json_encode(array('type'=>'error', 'text' => $lang[$language]['email_exists']));
				} else {
					$output = json_encode(array('type'=>'error', 'text' => $api->errorMessage));
					//errorLog("MailChimp","[".$api->errorCode."] ".$api->errorMessage);
					die($output);
				}
			}else{
				$output = json_encode(array('type'=>'message', 'text' => $lang[$language]['subscription']));
				die($output);
			}
		}
	}


	function sendCampaign($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){
		if(defined('CM_APIKEY') && defined('CM_LISTID')){
			require_once('api_campaign/CMBase.php');
			$api_key = CM_APIKEY;
			$client_id = null;
			$campaign_id = null;
			$list_id = CM_LISTID;
			$cm = new CampaignMonitor( $api_key, $client_id, $campaign_id, $list_id );
			$result = $cm->subscriberAddWithCustomFields($mailSubscribe, getName($mailSubscribe), $merge_vars, null, false);
			if($result['Code'] == 0){
				$output = json_encode(array('type'=>'message', 'text' => $lang[$language]['subscription']));
				die($output);
			}else{
				$output = json_encode(array('type'=>'error', 'text' => 'Error : ' . $result['Message']));
				die($output);
			}
		}else{
			$output = json_encode(array('type'=>'error', 'text' => 'Error: make sure that the API key and the list id are properly configured.'));
			die($output);
		}
	}

	function sendGetResponse($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){
		if(defined('GR_APIKEY') && defined('GR_CAMPAIGN')){
			require_once('api_getresponse/GetResponseAPI.class.php');
			$api = new GetResponse(GR_APIKEY);
			$campaign = $api->getCampaignByName(GR_CAMPAIGN);
			$subscribe = $api->addContact($campaign, getName($mailSubscribe), $mailSubscribe, 'standard', 0, $merge_vars);
			if($subscribe){
				$output = json_encode(array('type'=>'message', 'text' => $lang[$language]['subscription']));
				die($output);
			}else{
				$output = json_encode(array('type'=>'error', 'text' => $lang[$language]['email_exists']));
				die($output);
			}
		}else{
			$output = json_encode(array('type'=>'error', 'text' => 'Error: make sure that the API key and the list id are properly configured.'));
			die($output);
		}
	}

	function sendAWeber($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){
		if(defined('AW_AUTHCODE') && defined('AW_LISTNAME') && $merge_vars){
			require_once('api_aweber/aweber_api.php');
			$token = 'api_aweber/'. substr(AW_AUTHCODE, 0, 10);

			if(!file_exists($token)){
				try {
					$auth = AWeberAPI::getDataFromAweberID(AW_AUTHCODE);
					file_put_contents($token, json_encode($auth));
				} catch(AWeberAPIException $exc) {
					errorLog("AWeber","[".$exc->type."] ". $exc->message ." Docs: ". $exc->documentation_url);
					throw new Exception("Authorization error",5);
				}
			}

			if(file_exists($token)){
				$key = file_get_contents($token);
			}
			list($consumerKey, $consumerSecret, $accessToken, $accessSecret) = json_decode($key);

			$aweber = new AWeberAPI($consumerKey, $consumerSecret);
			try {
				$account = $aweber->getAccount($accessToken, $accessSecret);
				$foundLists = $account->lists->find(array('name' => AW_LISTNAME));
				$lists = $foundLists[0];


				if(!isset($merge_vars['name'])){
					$pix_extra['name'] = getName($mailSubscribe);
				}
				$custom_arr = array();
				foreach ($merge_vars as $variable => $v) {
					if($variable != 'name'){
						$custom_arr[filter_var($variable, FILTER_SANITIZE_STRING)] = filter_var($v, FILTER_SANITIZE_STRING);
					}
				}

				$params = array(
					'email' => $mailSubscribe,
					'name' => $merge_vars['name'],
					'custom_fields' => $custom_arr
				);

				if(isset($lists)){
					$lists->subscribers->create($params);
					$output = json_encode(array('type'=>'message', 'text' => $lang[$language]['subscription']));
					die($output);
				} else{
					//errorLog("AWeber","List is not found");
					$output = json_encode(array('type'=>'error', 'text' => 'Error: List is not found'));
					die($output);
					//throw new Exception("Error found Lists",4);
				}

			} catch(AWeberAPIException $exc) {
				if($exc->status == 400){
					//throw new Exception("Email exist",2);
					$output = json_encode(array('type'=>'error', 'text' => $lang[$language]['email_exists']));
					die($output);
				}else{
					//errorLog("AWeber","[".$exc->type."] ". $exc->message ." Docs: ". $exc->documentation_url);
					$output = json_encode(array('type'=>'error', 'text' => 'Error: '."[".$exc->type."] ". $exc->message ." Docs: ". $exc->documentation_url));
					die($output);
				}
			}
		}else{
			$output = json_encode(array('type'=>'error', 'text' => 'Error: AWeber configuration Error, please make sure that the API key and the list name are properly configured!'));
			die($output);
		}
	}


	function sendActiveCampaign($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){

		if(defined('ACTIVECAMPAIGN_URL') && defined('ACTIVECAMPAIGN_API_KEY') && defined('list_id')  ){
			require_once("api_activecampaign/ActiveCampaign.class.php");
			$ac = new ActiveCampaign(ACTIVECAMPAIGN_URL, ACTIVECAMPAIGN_API_KEY);
			if (!(int)$ac->credentials_test()) {
				$output = json_encode(array('type'=>'error', 'text' => 'Access denied: Invalid credentials (URL and/or API key).'));
				die($output);
			}
			$list_id = list_id;
			if(!isset($merge_vars['FIRSTNAME'])){
				$first_name = getName($mailSubscribe);
			}else{
				$first_name = $merge_vars['FIRSTNAME'];
			}
			if(!isset($merge_vars['LASTNAME'])){
				$last_name = "";
			}else{
				$last_name = $merge_vars['LASTNAME'];
			}
			// "CUSTOM1"            => "custom1111",
			//     "field[%CUSTOM1%,0]"  => "field value",
			$contact = array(
				"email"              => $mailSubscribe,
				"first_name"         => $first_name,
				"last_name"          => $last_name,
				"p[{$list_id}]"      => $list_id,
				"status[{$list_id}]" => 1, // "Active" status
			);
			foreach ($merge_vars as $k => $v) {
				if( strcasecmp($k, "email") && strcasecmp($k, "FIRSTNAME") && strcasecmp($k, "LASTNAME") ){
					$tkey = 'field[%'.$k.'%,0]';
				   $contact[$tkey] = $v;
				}
			}

			$contact_sync = $ac->api("contact/sync", $contact);

			if (!(int)$contact_sync->success) {
				// request failed
				$output = json_encode(array('type'=>'error', 'text' => "Syncing contact failed. Error returned: " . $contact_sync->error . " "));
				die($output);
			}
			// successful request
			$output = json_encode(array('type'=>'message', 'text' => $lang['EN']['subscription'] ));
			die($output);


		}else{
			$output = json_encode(array('type'=>'error', 'text' => 'Error: ActiveCampaign configuration Error, please check integration configuration'));
			die($output);
		}
	}


	function sendMailerLite($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){
		if(defined('MailerLite_API_KEY') && defined('MailerLite_LIST_ID')){
			require_once 'api_mailerlite/Base/RestBase.php';
			require_once 'api_mailerlite/Base/Rest.php';
			require_once 'api_mailerlite/Subscribers.php';
			$ML_Subscribers = new MailerLite\Subscribers( MailerLite_API_KEY );
			$name = getName($mailSubscribe);
			if(isset($merge_vars['name'])){
				$name = $merge_vars['name'];
			}
			$custom_fields = array();
			foreach ($merge_vars as $k => $v) {
				if( strcasecmp($k, "email") && strcasecmp($k, "name") ){
					$custom_fields[] = array( 'name' => $k, 'value' => $v );
				}
			}
			$subscriber = array(
			    'email' => $mailSubscribe,
			    'name' => $name,
			    'fields' => $custom_fields
			);
			$subscriber = $ML_Subscribers->setId( MailerLite_LIST_ID )->add( $subscriber );
			$res = json_decode($subscriber, true);
            if(array_key_exists('email', $res)&&$res['email'] == $mailSubscribe){
				$output = json_encode(array('type'=>'message', 'text' => $lang['EN']['subscription'] ));
			}else{
                $output = json_encode(array('type'=>'error', 'text' => 'Error:'. $res['message']));
			}
			die($output);
		}else{
			$output = json_encode(array('type'=>'error', 'text' => 'Error: AWeber configuration Error, please make sure that the API key and the list name are properly configured!'));
			die($output);
		}
	}

	function sendFreshMail($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){
		if(defined('FM_API_KEY') && defined('FM_API_SECRET') && defined('FM_list_id')) {
			require_once 'api_freshmail/class.rest.php';
			$rest = new FmRestAPI();
			$rest->setApiKey( FM_API_KEY );
			$rest->setApiSecret( FM_API_SECRET );

			$data = array(
			    'email' => $mailSubscribe,
			    'list'  => FM_list_id,
			    'custom_fields' => $merge_vars
			    //'state'   => 2
			    //'confirm' => 1
			);

			//testing transactional mail request
			try {
			    $response = $rest->doRequest('subscriber/add', $data);
			    // echo 'Subscriber added correctly, received data: ';
			    // print_r($response);
			    $output = json_encode(array('type'=>'message', 'text' => $lang['EN']['subscription'] ));
			    die($output);
			} catch (Exception $e) {
			    if($e->getCode()==1304){
			    	$output = json_encode(array('type'=>'error', 'text' => $lang[$language]['email_exists']));
					die($output);
			    }else{
			    	$output = json_encode(array('type'=>'error', 'text' => 'Error message: '.$e->getMessage().', Error code: '.$e->getCode().', HTTP code: '.$rest->getHttpCode()));
					die($output);
			    }
			}
		}else{
			$output = json_encode(array('type'=>'error', 'text' => 'Error: AWeber configuration Error, please make sure that the API key and the list name are properly configured!'));
			die($output);
		}
	}


	function sendSendloop($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){
		if(defined('Sendloop_API3_KEY') && defined('Sendloop_SUBDOMAIN')) {
			require 'api_sendloop/SendloopAPI3.php';
			if (!empty($_SERVER['HTTP_CLIENT_IP'])) {
			    $ip = $_SERVER['HTTP_CLIENT_IP'];
			} elseif (!empty($_SERVER['HTTP_X_FORWARDED_FOR'])) {
			    $ip = $_SERVER['HTTP_X_FORWARDED_FOR'];
			} else {
			    $ip = $_SERVER['REMOTE_ADDR'];
			}
			$sendloop = new SendloopAPI3(Sendloop_API3_KEY, Sendloop_SUBDOMAIN, 'json');
			$sendloop->run('List.GetList',array());
			$sendloop->run('Subscriber.Subscribe',array(
			    'EmailAddress'      => $mailSubscribe,
			    'ListID'            => 2,
			    'SubscriptionIP'    => $ip,
			    'Fields'            => array(
			        $merge_vars,
			    )
			    ));
			if($sendloop->Result['Success'] == true){
				$output = json_encode(array('type'=>'message', 'text' => $lang['EN']['subscription'] ));
			}else{
				$output = json_encode(array('type'=>'error', 'text' => 'Error: Sendloop configuration Error, please check config.php settings!'));
			}
			die($output);
		}
	}

	function sendMailWizz($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){
		if(defined('Mailwizz_apiUrl') && defined('Mailwizz_publicKey') && defined('Mailwizz_privateKey')) {
			require 'api_mailwizz/setup.php';
			$endpoint = new MailWizzApi_Endpoint_ListSubscribers();
			// CREATE / UPDATE EXISTING SUBSCRIBER
			$contact = array(
				"EMAIL" => $mailSubscribe
			);
			foreach ($merge_vars as $k => $v) {
				if( strcasecmp($k, "email") ){
				   $contact[$k] = $v;
				}
			}
			$response = $endpoint->createUpdate($the_list, $contact);
			$response   = $response->body;
			// if the returned status is success, we are done.
			if ($response->itemAt('status') == 'success') {
					$output = json_encode(array('type'=>'message', 'text' => $lang['EN']['subscription'] ));
					die($output);
			}
			// otherwise, the status is error
			$err_msg = $response->itemAt('error');
			if(is_array($response->itemAt('error'))){
					$err_msg = array_values($response->itemAt('error'));
			}
			$output = json_encode(array('type'=>'error', 'text' => $err_msg));
			die($output);
		}
	}

	function sendSendy($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){
		if(defined('Sendy_URL') && defined('Sendy_apikey') && defined('Sendy_listId')) {
			require_once 'api_sendy/Sendy.php';
			$config = [
				'sendyUrl' => Sendy_URL, // Your Sendy installation URL (without trailing slash).
				'apiKey'   => Sendy_apikey, // Your API key. Available in Sendy Settings.
				'listId'   => Sendy_listId,
			];

			// 3. Init.
			$sendy = new \SENDY\API( $config );

			$contact = array(
				"email" => $mailSubscribe
			);
			foreach ($merge_vars as $k => $v) {
				if( strcasecmp($k, "email") ){
				   $contact[$k] = $v;
				}
			}
			$responseArray = $sendy->subscribe($contact);

			if($responseArray['status']==true){
				$output = json_encode(array('type'=>'message', 'text' => $lang['EN']['subscription'] ));
				die($output);
			}else{
				$output = json_encode(array('type'=>'error', 'text' => "Erorr: Couldn't complete the subscription!"));
				$output = json_encode(array('type'=>'error', 'text' => $err_msg));
				die($output);
			}
		}
	}

	function sendHubspot($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){
		if(defined('Hubspot_api') && defined('Hubspot_list')) {
			require_once 'api_hubspot/Hubspot.php';

			$user = array();
			foreach ($merge_vars as $key => $value) {
			  array_push($user, array(
			    "property" => $key,
			    "value" => $value
			  ));
			}
			$hs = new Hubspot(Hubspot_api);
			$e = $hs->createUpdateContact($mailSubscribe, array( "properties" => $user));
			var_dump($e);
			if($e['status']==200 || $e['status']==409){
				$atl = array("emails" => array($mailSubscribe));
				$t = $hs->addToList($atl,Hubspot_list);
				$output = json_encode(array('type'=>'message', 'text' => $lang['EN']['subscription'] ));
				die($output);
			}else{
				$output = json_encode(array('type'=>'error', 'text' => "Error: ".$e['data']['message']));
				die($output);
			}

		}
	}

	function sendiContact($mailSubscribe, $the_list, $merge_vars=NULL, $language, $lang){
		if(defined('iContact_appId') && defined('iContact_apiPassword') && defined('iContact_apiUsername') && defined('iContact_list')) {
			require_once 'api_icontact/iContactApi.php';

			// Give the API your information
		  iContactApi::getInstance()->setConfig(array(
		  	'appId'       => iContact_appId,
		  	'apiPassword' => iContact_apiPassword,
		  	'apiUsername' => iContact_apiUsername
		  ));

		  // Store the singleton
		  $oiContact = iContactApi::getInstance();
		  // Try to make the call(s)
		  try {
		    $contact = $oiContact->addContact($mailSubscribe, $merge_vars);
		  	$res = $oiContact->subscribeContactToList($contact->contactId, iContact_list, 'normal');
				$output = json_encode(array('type'=>'message', 'text' => $lang['EN']['subscription'] ));
				die($output);
		  } catch (Exception $oException) {
				$output = json_encode(array('type'=>'error', 'text' => $oiContact->getErrors()));
				die($output);
		  }
		}
	}



	function errorLog($name,$desc){
		file_put_contents(ERROR_LOG, date("m.d.Y H:i:s")." (".$name.") ".$desc."\n", FILE_APPEND);
	}

	function getName($mail){
		preg_match("/([a-zA-Z0-9._-]*)@[a-zA-Z0-9._-]*$/",$mail,$matches);
        if(sizeof($matches)>=2){
            return $matches[1];
        }
        return "";
	}

?>
