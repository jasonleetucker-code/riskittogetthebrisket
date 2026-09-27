import {it,expect,vi,beforeEach} from "vitest";
const proxy=vi.hoisted(()=>vi.fn());
vi.mock("@/lib/backend-proxy",()=>({proxyGet:proxy}));
import {GET} from "@/app/api/bdvm/values/route";
beforeEach(()=>proxy.mockReset());
it("forwards board only with existing scope options and cookie; excludes arbitrary keys",async()=>{
 proxy.mockResolvedValue({data:{status:"ok",players:[]},status:200});
 const response=await GET({nextUrl:new URL("http://localhost/api/bdvm/values?view=board&leagueKey=test&surplusMode=plain&private=secret"),headers:new Headers({cookie:"session=test"})});
 expect(proxy).toHaveBeenCalledWith("/api/bdvm/values",{cookie:"session=test",searchParams:{view:"board",leagueKey:"test",surplusMode:"plain"},timeoutMs:30000});
 expect(await response.json()).toEqual({status:"ok",players:[]});
});
it("omitted view stays omitted and backend failures preserve status",async()=>{
 proxy.mockResolvedValue({data:{error:"feature_disabled"},status:503});
 const response=await GET({nextUrl:new URL("http://localhost/api/bdvm/values"),headers:new Headers()});
 expect(proxy.mock.calls[0][1].searchParams).toEqual({});expect(response.status).toBe(503);
 expect(await response.json()).toEqual({error:"feature_disabled"});
});

it("forwards an explicitly empty view for backend rejection, without changing other empty options",async()=>{
 proxy.mockResolvedValue({data:{error:"invalid_view"},status:400});
 const response=await GET({nextUrl:new URL("http://localhost/api/bdvm/values?view=&leagueKey=&surplusMode="),headers:new Headers()});
 expect(proxy.mock.calls[0][1].searchParams).toEqual({view:""});expect(response.status).toBe(400);
});
