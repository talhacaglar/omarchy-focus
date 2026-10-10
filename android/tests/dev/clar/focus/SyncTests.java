package dev.clar.focus;

import android.app.Instrumentation;
import android.os.Bundle;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.lang.reflect.*;
import java.util.*;

/** Device tests against an isolated desktop listener, never personal tasks. */
public class SyncTests extends Instrumentation {
    private int passed=0;
    private JSONObject pairing;
    private Store store;
    @Override public void onCreate(Bundle b) { super.onCreate(b); start(); }
    private void check(boolean ok,String label) {
        if(!ok) throw new AssertionError(label);
        passed++;
    }
    private JSONObject request(JSONArray ops) throws Exception {
        JSONObject r=new JSONObject(); r.put("protocol",1); r.put("dataset",pairing.getString("dataset")); r.put("operations",ops);
        Method post=Store.class.getDeclaredMethod("post",JSONObject.class,JSONObject.class); post.setAccessible(true);
        return (JSONObject)post.invoke(null,pairing,r);
    }
    private JSONObject remoteEdit(JSONObject task,String title) throws Exception {
        JSONObject fields=new JSONObject(); fields.put("title",title);
        JSONObject op=new JSONObject(); op.put("id",UUID.randomUUID().toString()); op.put("uid",task.getString("uid"));
        op.put("base",task.getInt("version")); op.put("kind","upsert"); op.put("fields",fields);
        return request(new JSONArray().put(op));
    }
    private JSONObject find(String title) {
        for(JSONObject t:store.list(false)) if(t.optString("title").equals(title)) return t;
        for(JSONObject t:store.list(true)) if(t.optString("title").equals(title)) return t;
        throw new AssertionError("Missing: "+title);
    }
    private void reload() throws Exception {
        Field f=Store.class.getDeclaredField("instance"); f.setAccessible(true); f.set(null,null);
        store=Store.get(getTargetContext());
    }
    @Override public void onStart() {
        Bundle result=new Bundle();
        try {
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            try(InputStream in=getContext().getAssets().open("pairing.json")) { byte[] b=new byte[1024]; int n; while((n=in.read(b))!=-1) out.write(b,0,n); }
            pairing=new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8));
            store=Store.get(getTargetContext());
            store.edit(null,"Offline test","Note","high","pending");
            check(store.pendingCount()==1,"offline queue");
            reload(); check(find("Offline test").optString("description").equals("Note"),"durable offline restart");
            store.pair(pairing.toString()); store.sync();
            check(store.pendingCount()==0,"upload acknowledged");
            check(request(new JSONArray()).getJSONArray("tasks").length()>=1,"desktop receives task");
            JSONObject t=find("Offline test");
            store.edit(t.getString("uid"),"Offline test","Note","high","done"); store.sync();
            check(find("Offline test").optString("status").equals("done"),"completion sync");
            store.edit(t.getString("uid"),"Offline test","Note","high","pending"); store.sync();
            check(find("Offline test").optString("status").equals("pending"),"reopen sync");
            t=find("Offline test"); remoteEdit(t,"Desktop test"); store.sync();
            check(find("Desktop test")!=null,"download desktop changes");
            t=find("Desktop test"); remoteEdit(t,"Concurrent desktop");
            store.edit(t.getString("uid"),"Concurrent phone","Note","high","pending"); store.sync();
            check(find("Concurrent phone").has("_conflict"),"concurrent edit detected");
            store.resolve(t.getString("uid"),true); store.sync();
            check(!find("Concurrent phone").has("_conflict") && store.pendingCount()==0,"explicit phone resolution");
            // A draft opened before a refresh must carry its original revision.
            t=find("Concurrent phone"); remoteEdit(t,"Desktop during dialog"); store.sync();
            store.edit(t.getString("uid"),"Stale dialog","Note","high","pending",t.getInt("version")); store.sync();
            check(find("Stale dialog").has("_conflict"),"open editor revision protected");
            store.resolve(t.getString("uid"),false);
            check(find("Desktop during dialog")!=null,"explicit desktop resolution");
            // An unreachable listener must not drop local changes.
            JSONObject offline=new JSONObject(pairing.toString()); offline.put("url","https://10.0.2.2:18769"); store.pair(offline.toString());
            store.edit(null,"Waiting for Wi-Fi","","medium","pending"); store.sync();
            check(store.pendingCount()==1,"network failure keeps pending edits");
            reload(); check(store.pendingCount()==1,"pending survives failed sync restart");
            store.pair(pairing.toString()); store.sync(); check(store.pendingCount()==0,"reconnection uploads edits");
            // Wrong pin and wrong token both fail closed.
            JSONObject wrong=new JSONObject(pairing.toString()); wrong.put("fingerprint",String.format("%064d",0));
            store.pair(wrong.toString()); store.edit(null,"Pin protected","","medium","pending"); store.sync();
            check(store.pendingCount()==1 && store.message().contains("kimliği"),"wrong TLS fingerprint rejected");
            wrong=new JSONObject(pairing.toString()); wrong.put("token","0000000000000000000000000000000000000000000");
            store.pair(wrong.toString()); store.sync();
            check(store.pendingCount()==1 && store.message().contains("anahtarı"),"wrong token rejected");
            store.pair(pairing.toString()); store.sync();
            t=find("Pin protected"); store.delete(t.getString("uid")); store.sync();
            check(store.pendingCount()==0,"delete acknowledged");
            boolean deleted=false;
            JSONArray all=request(new JSONArray()).getJSONArray("tasks");
            for(int i=0;i<all.length();i++) if(all.getJSONObject(i).getString("uid").equals(t.getString("uid"))) deleted=all.getJSONObject(i).getInt("deleted")==1;
            check(deleted,"desktop deletion tombstone");
            result.putString("stream","\nPASS: "+passed+" Android assertions\n"); finish(-1,result);
        } catch(Throwable e) {
            StringWriter s=new StringWriter(); e.printStackTrace(new PrintWriter(s));
            result.putString("stream","\nFAIL after "+passed+" assertions\n"+s); finish(0,result);
        }
    }
}
