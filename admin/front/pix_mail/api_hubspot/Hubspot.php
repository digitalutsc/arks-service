<?php

/**
 * SendGrid API v3 client library
 *
 * @author Voltroid
 */
class Hubspot
{

	private $api_key;
	private $api_url = 'https://api.hubapi.com';
	private $timeout = 8;
	public $http_status;

	/**
	* X-Domain header value if empty header will be not provided
	* @var string|null
	*/
	private $enterprise_domain = null;

	/**
	* X-APP-ID header value if empty header will be not provided
	* @var string|null
	*/
	private $app_id = null;

	/**
	* Set api key and optionally API endpoint
	* @param	$api_key
	* @param null $api_url
	*/
	public function __construct($api_key, $api_url = null)
	{
	$this->api_key = $api_key;

	if (!empty($api_url)) {
			$this->api_url = $api_url;
	}
	}

	/**
	* We can modify internal settings
	* @param $key
	* @param $value
	*/
	function __set($key, $value)
	{
	$this->{$key} = $value;
	}

	/**
	* get account details
	*
	* @return mixed
	*/
	public function test()
	{
	return $this->call('contacts/v1/lists');
	}

	/**
	* get Contact Lists
	*
	* @return mixed
	*/
	public function getLists()
	{
	return $this->call('contacts/v1/lists');
	}
	/**
	* get Custom Fields
	*
	* @return mixed
	*/
	public function getCustomFields()
	{
	return $this->call('properties/v1/contacts/properties');
	}
	/**
	* post Contact
	*
	* @return mixed
	*/
	public function addContact($data)
	{
	return $this->call('contacts/v1/contact','POST',$data);
	}

	public function createUpdateContact($email, $data)
	{
	return $this->call('contacts/v1/contact/createOrUpdate/email/'.$email,'POST',$data);
	}
	/**
	* post Contact
	*
	* @return mixed
	*/
	public function addToList($data,$list)
	{
	return $this->call('contacts/v1/lists/'.$list.'/add','POST',$data);
	}
	/**
	* post Contact
	*
	* @return mixed
	*/
	public function getContact($data)
	{
	return $this->call('contacts/v1/contact/email/'.$data.'/profile');
	}

	/**
	* Curl run request
	*
	* @param null $api_method
	* @param string $http_method
	* @param array $params
	* @return mixed
	* @throws Exception
	*/
	private function call($api_method = null, $http_method = 'GET', $params = array())
	{
	if (empty($api_method)) {
			return (object)array(
				'httpStatus' => '400',
				'code' => '1010',
				'codeDescription' => 'Error in external resources',
				'message' => 'Invalid api method'
			);
	}

	$gp = array(
			'hapikey' => $this->api_key
	);
	$gp = http_build_query($gp);
	$params = json_encode($params);
	$url = $this->api_url . '/' . $api_method. '?' . $gp;

	$options = array(
			CURLOPT_URL => $url,
			CURLOPT_ENCODING => 'gzip,deflate',
			CURLOPT_FRESH_CONNECT => 1,
			CURLOPT_RETURNTRANSFER => 1,
			CURLOPT_TIMEOUT => $this->timeout,
			CURLOPT_HEADER => false,
			CURLOPT_USERAGENT => 'PHP SendGrid client 0.0.1',
			CURLOPT_HTTPHEADER => array('Content-Type: application/json')
	);

	if(strlen(ini_get('curl.cainfo')) === 0) {
			$options[CURLOPT_CAINFO] = dirname(__FILE__).'/cacert.pem';
	}

	if ($http_method == 'POST') {
			$options[CURLOPT_CUSTOMREQUEST ] = 'POST';
			$options[CURLOPT_POSTFIELDS] = $params;
	} else if ($http_method == 'DELETE') {
			$options[CURLOPT_CUSTOMREQUEST] = 'DELETE';
	}

	$curl = curl_init();
	curl_setopt_array($curl, $options);

	$response = json_decode(curl_exec($curl),true);

	$this->http_status = curl_getinfo($curl, CURLINFO_HTTP_CODE);
	$resp=array(
		'data' => $response,
		'status' => $this->http_status
	);
	curl_close($curl);
	return $resp;
	}

	/**
	* @param array $params
	*
	* @return string
	*/
	private function setParams($params = array())
	{
	$result = array();
	if (is_array($params)) {
			foreach ($params as $key => $value) {
				$result[$key] = $value;
			}
	}
	return http_build_query($result);
	}

}
