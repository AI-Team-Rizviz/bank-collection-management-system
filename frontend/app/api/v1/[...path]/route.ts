import { NextRequest } from "next/server";
import { mockEnabled, routePermissions, can } from "@/lib/auth/policy";
import { getSession } from "@/lib/auth/server";
import { ApiError } from "@/lib/api/error";
import { ZodError } from "zod";
import type { ListParams } from "@/lib/api/types";
export const dynamic="force-dynamic";
async function handle(request:NextRequest,{params}:{params:Promise<{path:string[]}>}) {
 try {
  const {path}=await params;
  const allowed=["me","dashboard","users","roles","permissions","teams","scopes","access-requests","audit-logs","settings"];
  if(!allowed.includes(path[0])||path.length>3)throw new ApiError(404,"Endpoint not found");
  const session=await getSession();if(!session)throw new ApiError(401,"No verified IAM session. Connect the identity provider to continue.");
  if(!["GET","HEAD"].includes(request.method)&&request.headers.get("origin")!==request.nextUrl.origin)throw new ApiError(403,"Same-origin request required");
  const required=routePermissions[path[0]];if(required&&!can(session,required))throw new ApiError(403,"You do not have the required permission");
  if(mockEnabled()) {
   const {mockService}=await import("@/mocks/service");
   await new Promise(resolve=>setTimeout(resolve,180));
   if(request.headers.get("x-mock-failure")==="true")throw new ApiError(503,"Simulated IAM service interruption. Please retry.");
   const body=["POST","PATCH"].includes(request.method)?await request.json():{};
   return Response.json(await mockService().handle(request.method,path.join("/"),session,Object.fromEntries(request.nextUrl.searchParams) as ListParams,body),{headers:{"Cache-Control":"no-store"}});
  }
  // Proposed contracts are proxied without implementing IAM authorization in Next.js.
  const cookieName=process.env.IAM_SESSION_COOKIE??"__Host-iam_session";
  const token=request.cookies.get(cookieName)?.value;
  const headers:Record<string,string>={"Content-Type":"application/json",Cookie:`${cookieName}=${encodeURIComponent(token??"")}`};
  // Propagate the IdP's CSRF token when its cookie-based API requires one.
  const csrf=request.headers.get("x-csrf-token");if(csrf)headers["x-csrf-token"]=csrf;
  const response=await fetch(`${process.env.IAM_API_BASE_URL}/api/v1/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`,{method:request.method,headers,body:["GET","HEAD"].includes(request.method)?undefined:await request.text(),signal:AbortSignal.timeout(15000),cache:"no-store",redirect:"error"});
  if(!response.ok)throw new ApiError(response.status,response.status===403?"IAM denied this operation":"IAM could not complete the request");
  return new Response(response.status===204?null:await response.text(),{status:response.status,headers:{"Content-Type":"application/json","Cache-Control":"no-store"}});
 }catch(error){if(error instanceof ZodError)return Response.json({message:error.issues.map(i=>`${i.path.join(".")}: ${i.message}`).join("; ")},{status:422});if(error instanceof ApiError)return Response.json({message:error.message},{status:error.status});return Response.json({message:"IAM service is unavailable. Please retry."},{status:503});}
}
export {handle as GET,handle as POST,handle as PATCH,handle as DELETE};
