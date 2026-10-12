import { getJob } from '../../../../lib/jobs.mjs';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(request, context) {
  try {
    const {id}=await context.params;const data=await getJob(id);
    return data?Response.json(data):Response.json({error:'回测不存在'},{status:404});
  }catch(error){return Response.json({error:error.message},{status:400});}
}
