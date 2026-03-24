<?php defined('EXEC') or exit;
$page['title']="Project Lookup";

include __DIR__.'/../breadcrumb.php';

require_once FUNCTIONS.'/datatables.php';
$th=[];
$td=[];

$result=new AjeraAPI("ListProjects",[
    'FilterByStatus:["Preliminary","Active","Marketing"]'
]);
foreach($result->response->Content->Projects as $a){
    $a=(array)$a;

    if(empty($th)){
        $th=array_keys($a);
    }

    $a['ProjectKey']="<a href=\"{$module['redirect']}&view=get&ProjectKey={$a['ProjectKey']}\">{$a['ProjectKey']}</a>";
    $td[]=dtrow($a);
}

ob_start(); 
echo dttable(); ?>
<script>
$("#datatable").DataTable({
    columns:[<?=dtcols();?>],
    data:[<?=dtrows();?>],
    buttons:['csvHtml5'],
    dom:'Blfrtip',
    lengthMenu:[100,250,500],
    columnDefs:[]			
});	
</script><?php
echo widget(['content'=>ob_get_clean()]);
return;




require_once FUNCTIONS.'/form2022.php';
require_once FUNCTIONS.'/datatables.php';
$th=[];
$td=[];
$ProjectKey['options']=["<option></option>"];

$result=new AjeraAPI("ListProjects");
foreach($result->response->Content->Projects as $a){
    $a=(array)$a;

    // if(empty($th)){
    //     $th=array_keys($a);
    // }

    // $a['ProjectKey']="<a href=\"{$module['redirect']}&view=get&ProjectKey={$a['ProjectKey']}\">{$a['ProjectKey']}</a>";
    // $td[]=dtrow($a);

    $ProjectKey['options'][$a['ProjectKey']]="{$a['ProjectID']} {$a['Description']}";
} ?>

<?php
ob_start(); 
echo select('ProjectKey','Project Lookup',$ProjectKey);
echo widget(['content'=>ob_get_clean()]); 
include JS.'/select2/index.php'; ?>
<script>
$('#ProjectKey').select2();
</script>
