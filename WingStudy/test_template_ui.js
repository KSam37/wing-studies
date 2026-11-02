const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(__dirname+'/workflow.js','utf8'),lambda=fs.readFileSync(__dirname+'/lambda_review.js','utf8');
assert(source.includes('data-template-stl='));assert(source.includes("$('inspectTemplateStl').onclick="));assert(lambda.includes("$('templateStl').onclick="));
const target={},button={disabled:false,nextElementSibling:target};let sent,note;
const context={currentStudy:'fallback',esc:String,notify:m=>note=m,api:async(path,data)=>{sent={path,data};return {file:'study/case/template.zip',preview:'study/case/assembly.png',part_count:2,note:'2 mm lines × 3 mm high'};}};
vm.createContext(context);vm.runInContext(source.slice(source.indexOf('async function exportWingTemplate('),source.indexOf('function values(row)')),context);
(async()=>{
 await context.exportWingTemplate({_study:'chosen',id:'case_0001'},button);
 assert.equal(sent.path,'wing-template-stl');assert.equal(sent.data.study,'chosen');assert.equal(sent.data.case,'case_0001');assert.equal(button.disabled,false);assert(target.innerHTML.includes('Download 2 STL part(s)'));assert(note.includes('3 mm'));
 context.api=async()=>{throw Error('Unprintable chord bay');};await context.exportWingTemplate({id:'case_0001'},button);assert.equal(button.disabled,false);assert.equal(target.textContent,'Unprintable chord bay');
 console.log('Template buttons cover lambda details, standard rows and inspector; saved-case request, download and failure behavior passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
