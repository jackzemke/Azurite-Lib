<?php //defined('EXEC') or exit;
class AjeraAPI{
    private $credential;
    private $SessionToken;
    private $Method;
    private $Arguments;
    public $response;

    function __construct($method,$arguments=[],$company='SMA',$version=1){
        $this->SessionToken=file_get_contents(__DIR__."/../ds/AjeraAPISession.txt");
        $this->Method=$method;
        $this->Arguments=$arguments;
        // $response=$this->request();

        $credentials=[
            'SMA'=>[
                'url'=>'https://ajera.com/V004864/AjeraAPI.ashx?ew0KICAiQ2xpZW50SUQiOiA0ODY0LA0KICAiRGF0YWJhc2VJRCI6IDEyMzYsDQogICJJc1NhbXBsZURhdGEiOiBmYWxzZQ0KfQ%3d%3d',
                'username'=>'api_projects',
                'password'=>'1201Sma!',
                'site_id'=>1
            ],
            'Azurite'=>[
                'url'=>'https://ajera.com/V004864/AjeraAPI.ashx?ew0KICAiQ2xpZW50SUQiOiA0ODY0LA0KICAiRGF0YWJhc2VJRCI6IDMxOTQyLA0KICAiSXNTYW1wbGVEYXRhIjogZmFsc2UNCn0%3d',
                'username'=>'intranet',
                'password'=>'1201Sma!',
                'site_id'=>2
            ],
            'Gallatin'=>[
                'url'=>'https://ajera.com/V004864/AjeraAPI.ashx?ew0KICAiQ2xpZW50SUQiOiA0ODY0LA0KICAiRGF0YWJhc2VJRCI6IDE0NDkyLA0KICAiSXNTYW1wbGVEYXRhIjogZmFsc2UNCn0%3d',
                'username'=>'gallatin_intranet',
                'password'=>'1201Sma!',
                'site_id'=>3
            ],
            'IME'=>[
                'url'=>'https://ajera.com/V004864/AjeraAPI.ashx?ew0KICAiQ2xpZW50SUQiOiA0ODY0LA0KICAiRGF0YWJhc2VJRCI6IDI3NDUxLA0KICAiSXNTYW1wbGVEYXRhIjogZmFsc2UNCn0%3d',
                'username'=>'ime_intranet',
                'password'=>'1201Sma!',
                'site_id'=>4
            ]
        ];

        $this->credential=$credentials[$company];

        if($response->ResponseCode!=200){
            $response=$this->request("{
                Method: \"CreateAPISession\",
                Username: \"{$this->credential['username']}\",
                Password: \"{$this->credential['password']}\",
                APIVersion: {$version},
                UseSessionCookie: false
            }");
            
            if($response->ResponseCode==200){
                $this->SessionToken=$response->Content->SessionToken;
                file_put_contents(__DIR__."/../ds/AjeraAPISession.txt",$this->SessionToken);
                $response=$this->request();
            }
        }

        $this->response=$response;
    }

    function request($data=null){
        if(is_null($data)){
            $data="{
                Method:\"{$this->Method}\",
                SessionToken:\"{$this->SessionToken}\",
                MethodArguments:{".implode(',',$this->Arguments)."}
            }";
        }
        
        $options=[
            'http'=>[
                'method'=>'POST',
                'content'=>$data,
                'header'=>  
                    "Content-Type: application/json\r\n".
                    "Accept: application/json\r\n"
            ]
        ];

        $stream=stream_context_create($options);

        $contents=file_get_contents($this->credential['url'],false,$stream);
        return json_decode($contents); 
    }
}