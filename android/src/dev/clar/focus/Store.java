package dev.clar.focus;

import android.content.Context;
import android.util.AtomicFile;
import org.json.*;
import java.io.*;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.cert.X509Certificate;
import java.util.*;
import javax.net.ssl.*;

/** Local state and pending edits are committed together, before a network attempt. */
public final class Store {
    private static Store instance;
    private final AtomicFile file;
    private JSONObject state;
    private boolean syncing;
    private String message = "";

    public static synchronized Store get(Context c) {
        if (instance == null) instance = new Store(c.getApplicationContext());
        return instance;
    }
    private Store(Context c) {
        file = new AtomicFile(new File(c.getFilesDir(), "tasks.json"));
        try {
            state = new JSONObject(new String(file.readFully(), StandardCharsets.UTF_8));
        } catch (FileNotFoundException e) {
            state = new JSONObject();
            put(state, "tasks", new JSONObject());
        } catch (Exception e) {
            // Never silently replace an unreadable store with an empty database.
            throw new IllegalStateException("Görev dosyası okunamadı; veriler korunuyor.", e);
        }
    }
    static void put(JSONObject o, String k, Object v) {
        try { o.put(k, v); } catch (JSONException e) { throw new IllegalArgumentException(e); }
    }
    static JSONObject copy(JSONObject o) {
        try { return new JSONObject(o.toString()); } catch (JSONException e) { throw new IllegalArgumentException(e); }
    }
    private JSONObject tasks() { return state.optJSONObject("tasks"); }
    private void save() {
        FileOutputStream out = null;
        try {
            out = file.startWrite();
            out.write(state.toString().getBytes(StandardCharsets.UTF_8));
            file.finishWrite(out);
        } catch (IOException e) {
            if (out != null) file.failWrite(out);
            throw new IllegalStateException("Görevler kaydedilemedi. Depolama alanını kontrol et.", e);
        }
    }
    public synchronized boolean paired() { return state.optJSONObject("pairing") != null; }
    public synchronized boolean busy() { return syncing; }
    public synchronized String message() { return message; }
    public synchronized String lastSync() { return state.optString("lastSync", "Henüz eşitlenmedi"); }
    public synchronized int pendingCount() {
        int count = 0;
        Iterator<String> keys = tasks().keys();
        while(keys.hasNext()) if(tasks().optJSONObject(keys.next()).has("_pending")) count++;
        return count;
    }
    public synchronized List<JSONObject> list(boolean completed) {
        List<JSONObject> result = new ArrayList<>();
        Iterator<String> keys = tasks().keys();
        while(keys.hasNext()) {
            JSONObject t = tasks().optJSONObject(keys.next());
            boolean hidden = t.optInt("deleted") == 1 || "archived".equals(t.optString("status"));
            boolean done = "done".equals(t.optString("status"));
            if (t.has("_conflict") || (!hidden && done == completed)) result.add(copy(t));
        }
        Collections.sort(result, (a,b) -> {
            int ac = a.has("_conflict") ? 0 : 1, bc = b.has("_conflict") ? 0 : 1;
            if(ac != bc) return ac - bc;
            int ap = "high".equals(a.optString("priority")) ? 0 : "low".equals(a.optString("priority")) ? 2 : 1;
            int bp = "high".equals(b.optString("priority")) ? 0 : "low".equals(b.optString("priority")) ? 2 : 1;
            return ap != bp ? ap-bp : a.optString("title").compareToIgnoreCase(b.optString("title"));
        });
        return result;
    }
    public synchronized void edit(String uid, String title, String description, String priority, String status) {
        edit(uid,title,description,priority,status,-1);
    }
    public synchronized void edit(String uid, String title, String description, String priority, String status, int sourceVersion) {
        if(title.trim().isEmpty() || title.length() > 500 || description.length() > 20000)
            throw new IllegalArgumentException("Başlık 1–500, not en fazla 20.000 karakter olmalı.");
        if(uid == null) uid = UUID.randomUUID().toString();
        JSONObject t = tasks().optJSONObject(uid);
        if(t == null) { t = new JSONObject(); put(t,"uid",uid); put(t,"version",0); }
        put(t,"title",title.trim()); put(t,"description",description);
        put(t,"priority",priority); put(t,"status",status); put(t,"deleted",0);
        JSONObject previous=t.optJSONObject("_pending");
        queue(t,"upsert");
        if(previous == null && sourceVersion >= 0) put(t.optJSONObject("_pending"),"base",sourceVersion);
        put(tasks(),uid,t); save();
    }
    private void queue(JSONObject t, String kind) {
        JSONObject old = t.optJSONObject("_pending");
        int base = old == null ? t.optInt("version") : old.optInt("base");
        JSONObject fields = new JSONObject();
        if(kind.equals("upsert")) for(String k : new String[]{"title","description","priority","status"})
            put(fields,k,t.optString(k));
        JSONObject op = new JSONObject();
        put(op,"id",UUID.randomUUID().toString()); put(op,"uid",t.optString("uid"));
        put(op,"base",base); put(op,"kind",kind); put(op,"fields",fields);
        put(t,"_pending",op);
    }
    public synchronized void delete(String uid) {
        JSONObject t = tasks().optJSONObject(uid);
        if(t == null) return;
        // Keep even unsent deletions: a previous request may have reached the PC.
        put(t,"deleted",1); queue(t,"delete"); save();
    }
    public synchronized void resolve(String uid, boolean keepPhone) {
        JSONObject t = tasks().optJSONObject(uid);
        JSONObject remote = t.optJSONObject("_conflict");
        if(remote == null) return;
        if(!keepPhone) put(tasks(),uid,copy(remote));
        else if(remote.optInt("deleted") == 1 || remote.optInt("version") == 0) {
            // Preserve the phone content as a NEW task, never resurrect a tombstone.
            JSONObject local = copy(t);
            put(tasks(),uid,copy(remote));
            if(local.optInt("deleted") != 1)
                edit(null,local.optString("title"),local.optString("description"),local.optString("priority"),local.optString("status"));
        } else {
            t.remove("_conflict"); t.remove("_pending");
            put(t,"version",remote.optInt("version"));
            queue(t,t.optInt("deleted") == 1 ? "delete" : "upsert");
        }
        save();
    }
    public synchronized void pair(String json) throws Exception {
        JSONObject p = new JSONObject(json);
        URL url = new URL(p.getString("url"));
        if(p.optInt("protocol") != 1 || !"https".equals(url.getProtocol()) || url.getUserInfo() != null
            || !url.getPath().isEmpty() || url.getQuery() != null || url.getRef() != null
            || !p.getString("fingerprint").matches("[0-9a-f]{64}")
            || !p.getString("token").matches("[A-Za-z0-9_-]{32,128}")
            || !p.getString("dataset").matches("[0-9a-f]{32}"))
            throw new IllegalArgumentException("Geçerli bir eşleştirme dosyası seç.");
        JSONObject old = state.optJSONObject("pairing");
        if(old != null && !old.optString("dataset").equals(p.getString("dataset")))
            throw new IllegalArgumentException("Bu dosya başka bir görev veritabanına ait. Mevcut görevler korundu.");
        if(syncing) throw new IllegalStateException("Eşitlemenin bitmesini bekle.");
        put(state,"pairing",p); message="Bilgisayar eşleştirildi"; save();
    }
    public void sync() {
        JSONObject pairing, sent = new JSONObject(), request = new JSONObject();
        synchronized(this) {
            if(syncing || !paired()) return;
            syncing=true; message="Eşitleniyor…";
            pairing=copy(state.optJSONObject("pairing"));
            JSONArray operations=new JSONArray();
            Iterator<String> keys=tasks().keys();
            while(keys.hasNext() && operations.length() < 500) {
                JSONObject t=tasks().optJSONObject(keys.next());
                if(t.has("_pending") && !t.has("_conflict")) {
                    JSONObject op=copy(t.optJSONObject("_pending"));
                    if(operations.toString().length()+op.toString().length() > 200000) break;
                    operations.put(op); put(sent,t.optString("uid"),op);
                }
            }
            put(request,"protocol",1); put(request,"dataset",pairing.optString("dataset"));
            put(request,"operations",operations);
        }
        try {
            JSONObject response=post(pairing,request);
            synchronized(this) { apply(response,sent); message="Görevler eşitlendi"; }
        } catch(Exception e) {
            synchronized(this) {
                message=e instanceof SSLException ? "Bilgisayarın kimliği doğrulanamadı. Yeniden eşleştir."
                    : e instanceof SecurityException ? e.getMessage()
                    : "Bilgisayara ulaşılamadı. Görevlerin telefonda kayıtlı; aynı Wi-Fi'da tekrar denenecek.";
            }
        } finally { synchronized(this) { syncing=false; } }
    }
    private void apply(JSONObject response, JSONObject sent) throws Exception {
        if(response.getInt("protocol") != 1 || !response.getString("dataset").equals(state.optJSONObject("pairing").getString("dataset")))
            throw new SecurityException("Farklı bilgisayar veritabanı. Yeniden eşleştir.");
        Set<String> accepted=new HashSet<>(), conflicts=new HashSet<>();
        JSONArray a=response.getJSONArray("accepted"), c=response.getJSONArray("conflicts");
        for(int i=0;i<a.length();i++) accepted.add(a.getString(i));
        for(int i=0;i<c.length();i++) conflicts.add(c.getString(i));
        JSONArray remoteTasks=response.getJSONArray("tasks");
        for(int i=0;i<remoteTasks.length();i++) {
            JSONObject remote=remoteTasks.getJSONObject(i); String uid=remote.getString("uid");
            JSONObject local=tasks().optJSONObject(uid), op=sent.optJSONObject(uid);
            if(local == null || !local.has("_pending")) { put(tasks(),uid,remote); continue; }
            JSONObject pending=local.getJSONObject("_pending");
            if(op != null && accepted.contains(op.getString("id"))) {
                if(pending.getString("id").equals(op.getString("id"))) { put(tasks(),uid,remote); continue; }
                int expected=op.getInt("base") == 0 ? (op.getString("kind").equals("delete") ? 1 : 2) : op.getInt("base")+1;
                if(remote.optInt("version") == expected && remote.optInt("deleted") == 0) {
                    put(pending,"base",remote.getInt("version")); put(local,"version",remote.getInt("version"));
                } else put(local,"_conflict",remote);
            } else if(conflicts.contains(uid) || local.has("_conflict")) put(local,"_conflict",remote);
        }
        // A database restored from an old backup may no longer contain a known UID.
        for(String uid:conflicts) {
            JSONObject local=tasks().optJSONObject(uid);
            if(local != null && !local.has("_conflict")) {
                JSONObject missing=new JSONObject(); put(missing,"uid",uid); put(missing,"version",0); put(missing,"deleted",1);
                put(local,"_conflict",missing);
            }
        }
        put(state,"lastSync",new java.text.SimpleDateFormat("HH:mm · dd MMM",new Locale("tr")).format(new Date()));
        save();
    }
    private static JSONObject post(JSONObject p, JSONObject request) throws Exception {
        final String fingerprint=p.getString("fingerprint");
        X509TrustManager trust=new X509TrustManager() {
            public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
            public void checkClientTrusted(X509Certificate[] chain,String auth) throws java.security.cert.CertificateException { throw new java.security.cert.CertificateException(); }
            public void checkServerTrusted(X509Certificate[] chain,String auth) throws java.security.cert.CertificateException {
                try {
                    if(chain.length == 0) throw new Exception();
                    byte[] digest=MessageDigest.getInstance("SHA-256").digest(chain[0].getEncoded());
                    StringBuilder actual=new StringBuilder();
                    for(byte b:digest) actual.append(String.format(Locale.US,"%02x",b & 255));
                    if(!MessageDigest.isEqual(actual.toString().getBytes(StandardCharsets.US_ASCII),fingerprint.getBytes(StandardCharsets.US_ASCII))) throw new Exception();
                    chain[0].checkValidity();
                } catch(Exception e) { throw new java.security.cert.CertificateException("Unpaired certificate",e); }
            }
        };
        SSLContext tls=SSLContext.getInstance("TLS"); tls.init(null,new TrustManager[]{trust},null);
        HttpsURLConnection connection=(HttpsURLConnection)new URL(p.getString("url")+"/v1/exchange").openConnection();
        connection.setSSLSocketFactory(tls.getSocketFactory());
        // Identity is the exact pinned certificate, independent of changing LAN IPs.
        connection.setHostnameVerifier((host,session) -> {
            try { trust.checkServerTrusted(Arrays.copyOf(session.getPeerCertificates(),session.getPeerCertificates().length,X509Certificate[].class),"RSA"); return true; }
            catch(Exception e) { return false; }
        });
        connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(5000); connection.setReadTimeout(10000);
        connection.setRequestMethod("POST"); connection.setDoOutput(true);
        connection.setRequestProperty("Authorization","Bearer "+p.getString("token"));
        connection.setRequestProperty("Content-Type","application/json");
        byte[] data=request.toString().getBytes(StandardCharsets.UTF_8);
        connection.setFixedLengthStreamingMode(data.length);
        try {
            try(OutputStream out=connection.getOutputStream()) { out.write(data); }
            int code=connection.getResponseCode();
            if(code == 401) throw new SecurityException("Eşleştirme anahtarı geçersiz. Yeniden eşleştir.");
            if(code == 400) throw new SecurityException("Eşitleme isteği reddedildi. Görevlerin korundu; bilgisayarla eşleştirmeyi kontrol et.");
            if(code != 200) throw new IOException("HTTP "+code);
            try(InputStream in=connection.getInputStream(); ByteArrayOutputStream out=new ByteArrayOutputStream()) {
                byte[] buffer=new byte[8192]; int n;
                while((n=in.read(buffer)) != -1) { if(out.size()+n > 16*1024*1024) throw new IOException("Response too large"); out.write(buffer,0,n); }
                return new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8));
            }
        } finally { connection.disconnect(); }
    }
}
