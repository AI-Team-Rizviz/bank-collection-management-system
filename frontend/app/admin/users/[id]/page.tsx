import { UserDetail } from "@/features/users/user-detail";
export default async function Page({params}:{params:Promise<{id:string}>}){const {id}=await params;return <UserDetail id={id}/>;}
