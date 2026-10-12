import { catalog, defaults } from '../../../lib/config.mjs';
import { listJobs, startJob } from '../../../lib/jobs.mjs';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET() {
  try{return Response.json({catalog,defaults,jobs:await listJobs()});}
  catch(error){return Response.json({error:error.message},{status:500});}
}
export async function POST(request) {
  const origin=request.headers.get('origin');
  // Next生产服务器内部URL可能使用localhost；浏览器实际来源以Host头为准。
  const expectedOrigin=`http://${request.headers.get('host')}`;
  if(origin&&origin!==expectedOrigin)return Response.json({error:'请求来源无效'},{status:403});
  if(!request.headers.get('content-type')?.includes('application/json'))return Response.json({error:'请提交JSON参数'},{status:415});
  try{return Response.json({job:await startJob(await request.json())},{status:202});}
  catch(error){return Response.json({error:error.message},{status:error.status||400});}
}
