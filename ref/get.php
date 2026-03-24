<?php defined('EXEC') or exit; 

$b=new Breadcrumb();
$b->add('Back to Project Lookup',"?module=MyAccount/ProjectLookup");
echo $b;

require_once FUNCTIONS.'/datatables.php';
$th=[
    'Key',
    'ID',
    'Description',
    'Status',
    'Formatted Phase Description for Import'
];
$td=[];

$result=new AjeraAPI('GetProjects',[
    'RequestedProjects:['.$_GET['ProjectKey'].']',
    ''
]);

$project=$result->response->Content->Projects[0];
foreach($project->InvoiceGroups as $ig){
    phases($ig->Phases,$project->ProjectKey,$project->Description);
}

$page['title']="Phases for {$project->ID} {$project->Description}";

ob_start();
echo dttable(); ?>
<script>
$('#datatable').DataTable({
    columns:[<?=dtcols();?>],
    data:[<?=dtrows();?>],
    dom:'Blftip',
    buttons:[
        {extend:'csvHtml5',filename:"ProjectLookup-<?=$_GET['ProjectKey'];?>"}
    ],
    ordering:false,
    paging:false,
    columnDefs:[
        {class:'filter',targets:[3]}
    ]
});

$('a.copy').on('click',function(e){
    e.preventDefault();
    text=$(this).data('text');
    temp=$('<textarea>');
    $('body').append(temp);
    temp.val(text).select();
    document.execCommand('copy');
    temp.remove();
});
</script><?php 
echo widget(['content'=>ob_get_clean()]);

function phases($phases,$parent,$level=1,$predescription=''){
    global $td;

    foreach($phases as $p){
        $fulldescription=trim("{$predescription}\\\\{$p->Description}",'\\\\');
        $td[]=dtrow([
            a('',i('copy'),['class'=>'copy','data-text'=>$p->PhaseKey]).$p->PhaseKey.' ',
            str_repeat(" - ",$level).$p->ID,
            str_repeat(' - ',$level).$p->Description,
            $p->Status,
            $fulldescription
        ]);
        phases($p->Phases,$p->PhaseKey,$level+1,$fulldescription);
    }
}