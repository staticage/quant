// 本地任务调度层只启动uv/Freqtrade子进程，状态与日志落盘，页面刷新不丢任务。
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { runnerArguments, validateConfig } from './config.mjs';

export const root = path.resolve(process.env.QUANT_ROOT || path.join(process.cwd(),'..'));
const runs = path.join(root,'user_data','ui-runs');
const lockPath = path.join(runs,'active.lock');
const running = new Set(['queued','running']);
async function json(file) { try{return JSON.parse(await fs.readFile(file,'utf8'));}catch(error){if(error.code==='ENOENT')return null;throw error;} }
async function save(file,value) { const temp=`${file}.${randomUUID()}.tmp`;await fs.writeFile(temp,JSON.stringify(value,null,2));await fs.rename(temp,file); }
function alive(pid) { if(!Number.isInteger(pid))return false;try{process.kill(pid,0);return true;}catch{return false;} }
function directory(id) { if(!/^[a-f0-9-]{36}$/.test(id))throw new Error('任务ID无效');return path.join(runs,id); }

async function reconcile(job,dir) {
  if(running.has(job.status)&&!alive(job.pid||job.ownerPid)) {
    // 服务器或子进程异常退出时，保留失败记录，不能展示旧结果为本次成功。
    const result=await json(path.join(dir,'summary.json'));
    job={...job,status:result?'completed':'failed',finishedAt:new Date().toISOString(),
      error:result?null:'运行进程已结束，未生成完整结果。请重新运行。'};
    await save(path.join(dir,'job.json'),job);
  }
  return job;
}
export async function listJobs() {
  await fs.mkdir(runs,{recursive:true});
  const entries=await fs.readdir(runs,{withFileTypes:true});
  const jobs=[];
  for(const item of entries.filter(x=>x.isDirectory())) {
    const dir=path.join(runs,item.name);const job=await json(path.join(dir,'job.json'));
    if(job)jobs.push(await reconcile(job,dir));
  }
  const baseline=await json(path.join(root,'reports','summary.json'));
  if(baseline?.run?.status==='completed')jobs.push({id:'baseline',status:'completed',
    createdAt:baseline.run.created_at,config:{...baseline.run.arguments,skipDownload:baseline.run.arguments.skip_download},label:'首次一年回测'});
  return jobs.sort((a,b)=>b.createdAt.localeCompare(a.createdAt));
}
export async function getJob(id) {
  if(id==='baseline')return {job:(await listJobs()).find(j=>j.id==='baseline'),
    result:await json(path.join(root,'reports','summary.json')),logs:'已有Freqtrade回测结果已导入。'};
  const dir=directory(id);const original=await json(path.join(dir,'job.json'));
  if(!original)return null;
  const job=await reconcile(original,dir);
  let logs='';try{logs=(await fs.readFile(path.join(dir,'run.log'),'utf8')).slice(-20000);}catch(error){if(error.code!=='ENOENT')throw error;}
  const result=job.status==='completed'?await json(path.join(dir,'summary.json')):null;
  return {job,result,logs};
}
export async function startJob(input) {
  const config=validateConfig(input);
  await fs.mkdir(runs,{recursive:true});
  // 文件锁跨Next开发热更新/进程生效：共享行情目录同一时刻仅运行一个任务。
  let lock;
  for(let attempt=0;attempt<2;attempt++) {
    try{lock=await fs.open(lockPath,'wx');break;}catch(error){
      if(error.code!=='EEXIST')throw error;
      let active;try{active=await json(lockPath);}catch{throw Object.assign(new Error('已有任务正在启动，请稍后重试'),{status:409});}
      if(!active || alive(active.pid)||alive(active.ownerPid))throw Object.assign(new Error('已有回测正在运行，请等待完成'),{status:409});
      await fs.unlink(lockPath);
    }
  }
  if(!lock)throw Object.assign(new Error('已有回测正在运行'),{status:409});
  const id=randomUUID();const dir=directory(id);await fs.mkdir(dir);
  let job={id,status:'queued',createdAt:new Date().toISOString(),config,ownerPid:process.pid};
  await lock.writeFile(JSON.stringify({id,ownerPid:process.pid}));await lock.close();
  try {
    await save(path.join(dir,'job.json'),job);
    const log=await fs.open(path.join(dir,'run.log'),'a');
    const child=spawn(/* turbopackIgnore: true */ process.env.UV_BIN||'uv',runnerArguments(config,dir),{
      cwd:root,env:{...process.env,UV_CACHE_DIR:path.join(root,'.cache','uv'),PYTHONUNBUFFERED:'1',NO_COLOR:'1'},
      shell:false,stdio:['ignore',log.fd,log.fd]});
    let settled=false;
    async function finish(error,code) {
      if(settled)return;settled=true;
      try {
        const result=await json(path.join(dir,'summary.json'));
        const completed=!error&&code===0&&result?.run?.status==='completed';
        job={...job,status:completed?'completed':'failed',finishedAt:new Date().toISOString(),
          error:completed?null:error?.message||`Freqtrade未完成回测（退出码${code}），请查看日志。`};
        await save(path.join(dir,'job.json'),job);
      }finally {
        await log.close();const current=await json(lockPath);if(current?.id===id)await fs.unlink(lockPath);
      }
    }
    child.once('error',error=>{void finish(error,null).catch(console.error)});
    child.once('close',code=>{void finish(null,code).catch(console.error)});
    job={...job,status:'running',pid:child.pid};
    await save(path.join(dir,'job.json'),job);
    await save(lockPath,{id,pid:child.pid,ownerPid:process.pid});
    return job;
  }catch(error){await fs.unlink(lockPath).catch(()=>{});throw error;}
}
