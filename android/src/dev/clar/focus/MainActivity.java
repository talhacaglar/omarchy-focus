package dev.clar.focus;

import android.app.*;
import android.content.*;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.List;

public final class MainActivity extends Activity {
    private static final int BG=0xff171b22, PANEL=0xff222832, TEXT=0xffeef1f5, MUTED=0xffa9b2be, GOLD=0xffd7b879;
    private Store store;
    private LinearLayout root, rows;
    private TextView syncLabel, countLabel;
    private Button pendingTab, doneTab;
    private boolean completed=false, resumed=false;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Runnable tick=new Runnable() { public void run() { if(resumed) { sync(); handler.postDelayed(this,20000); } } };
    private int dp(int n) { return (int)(n*getResources().getDisplayMetrics().density+.5f); }
    private TextView text(String value,int size,int color) {
        TextView v=new TextView(this); v.setText(value); v.setTextSize(size); v.setTextColor(color);
        v.setPadding(0,dp(4),0,dp(4)); return v;
    }
    private GradientDrawable background(int color,int radius) {
        GradientDrawable d=new GradientDrawable(); d.setColor(color); d.setCornerRadius(dp(radius)); return d;
    }
    private Button button(String title,View.OnClickListener action) {
        Button b=new Button(this); b.setText(title); b.setAllCaps(false); b.setTextColor(TEXT);
        b.setTextSize(14); b.setMinHeight(dp(48)); b.setOnClickListener(action);
        android.graphics.drawable.RippleDrawable ripple=new android.graphics.drawable.RippleDrawable(
            android.content.res.ColorStateList.valueOf(0x33d7b879),background(PANEL,10),null);
        b.setBackground(new android.graphics.drawable.InsetDrawable(ripple,dp(3))); return b;
    }
    private LinearLayout vertical() { LinearLayout v=new LinearLayout(this); v.setOrientation(LinearLayout.VERTICAL); return v; }
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        store=Store.get(this); SyncJob.schedule(this);
        root=vertical(); root.setBackgroundColor(BG); root.setPadding(dp(22),dp(12),dp(22),dp(12));
        root.setOnApplyWindowInsetsListener((view,insets) -> {
            view.setPadding(dp(22)+insets.getSystemWindowInsetLeft(),dp(12)+insets.getSystemWindowInsetTop(),
                dp(22)+insets.getSystemWindowInsetRight(),dp(12)+insets.getSystemWindowInsetBottom()); return insets;
        });
        TextView brand=text("CLAR / FOCUS",12,GOLD); brand.setLetterSpacing(.16f); root.addView(brand);
        TextView title=text("Görevlerin",32,TEXT);
        title.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL)); title.setPadding(0,dp(14),0,dp(12)); root.addView(title);
        // The quiet sync strip always distinguishes local storage from delivery.
        syncLabel=text("",12,MUTED); root.addView(syncLabel);
        LinearLayout controls=new LinearLayout(this);
        controls.addView(button("Eşitle",v -> sync()),new LinearLayout.LayoutParams(0,dp(52),1));
        controls.addView(button("Bilgisayarı bağla",v -> pair()),new LinearLayout.LayoutParams(0,dp(52),1));
        root.addView(controls);
        LinearLayout tabs=new LinearLayout(this);
        pendingTab=button("Yapılacaklar",v -> { completed=false; render(); });
        doneTab=button("Tamamlananlar",v -> { completed=true; render(); });
        tabs.addView(pendingTab,new LinearLayout.LayoutParams(0,dp(52),1));
        tabs.addView(doneTab,new LinearLayout.LayoutParams(0,dp(52),1));
        root.addView(tabs);
        countLabel=text("",13,GOLD); root.addView(countLabel);
        ScrollView scroll=new ScrollView(this); scroll.setFillViewport(true);
        rows=vertical(); scroll.addView(rows);
        root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        Button add=button("+  Görev ekle",v -> editor(null)); add.setTextColor(BG); add.setBackground(background(GOLD,14));
        LinearLayout.LayoutParams addParams=new LinearLayout.LayoutParams(-1,dp(56)); addParams.topMargin=dp(12); root.addView(add,addParams);
        setContentView(root); render();
    }
    @Override public void onResume() { super.onResume(); resumed=true; handler.post(tick); }
    @Override public void onPause() { resumed=false; handler.removeCallbacks(tick); super.onPause(); }
    private void sync() {
        if(!store.paired()) { render(); return; }
        if(store.busy()) return;
        new Thread(() -> { store.sync(); runOnUiThread(() -> { if(!isDestroyed()) render(); }); },"clar-sync").start();
        handler.postDelayed(() -> { if(!isDestroyed()) updateStatus(); },100);
    }
    private void updateStatus() {
        int count=store.pendingCount();
        String s=!store.paired() ? "Telefonda kayıtlı · eşitlemek için bilgisayarını bağla"
            : store.busy() ? "Bilgisayarla eşitleniyor…"
            : count > 0 ? count+" değişiklik telefonda kayıtlı · eşitlenmeyi bekliyor"
            : "Son eşitleme: "+store.lastSync();
        if(!store.busy() && !store.message().isEmpty()) s+="\n"+store.message();
        syncLabel.setText(s);
    }
    private void render() {
        updateStatus(); rows.removeAllViews();
        pendingTab.setTextColor(completed ? MUTED : GOLD); doneTab.setTextColor(completed ? GOLD : MUTED);
        List<JSONObject> tasks=store.list(completed);
        countLabel.setText((completed ? "TAMAMLANAN" : "YAPILACAK")+" · "+tasks.size());
        if(tasks.isEmpty()) {
            TextView empty=text(completed ? "Tamamladığın görevler burada görünür." : "Şu an listen boş.\nAklındaki ilk işi ekle.",20,MUTED);
            empty.setPadding(0,dp(38),0,0); rows.addView(empty); return;
        }
        for(JSONObject t:tasks) {
            LinearLayout card=vertical(); card.setPadding(dp(16),dp(12),dp(16),dp(12)); card.setBackground(background(PANEL,14));
            LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2); p.topMargin=dp(8); rows.addView(card,p);
            String priority=t.optString("priority"), status=t.optString("status");
            String label=priority.equals("high") ? "Yüksek öncelik" : priority.equals("low") ? "Düşük öncelik" : "Normal öncelik";
            if(status.equals("in_progress")) label+=" · Devam ediyor";
            if(t.has("_pending")) label+=" · Telefonda";
            card.addView(text(label,11,GOLD));
            TextView title=text(t.optString("title"),20,TEXT); card.addView(title);
            if(!t.optString("description").isEmpty()) { TextView desc=text(t.optString("description"),14,MUTED); desc.setMaxLines(3); card.addView(desc); }
            if(t.has("_conflict")) {
                card.addView(text("Bu görev iki cihazda da değişti.",13,GOLD));
                card.addView(button("Değişiklikleri karşılaştır",v -> conflict(t)));
            } else {
                LinearLayout actions=new LinearLayout(this);
                actions.addView(button(status.equals("done") ? "Geri aç" : "Tamamla",v -> {
                    store.edit(t.optString("uid"),t.optString("title"),t.optString("description"),priority,status.equals("done") ? "pending" : "done",t.optInt("version"));
                    render(); sync();
                }),new LinearLayout.LayoutParams(0,dp(48),1));
                actions.addView(button("Düzenle",v -> editor(t)),new LinearLayout.LayoutParams(0,dp(48),1));
                card.addView(actions);
            }
        }
    }
    private EditText input(String hint,String initial,int lines) {
        EditText e=new EditText(this); e.setHint(hint); e.setText(initial); e.setTextColor(TEXT); e.setHintTextColor(MUTED);
        e.setTextSize(16); e.setMinLines(lines); e.setMaxLines(lines == 1 ? 3 : 6);
        e.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_FLAG_CAP_SENTENCES | android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        return e;
    }
    private void editor(JSONObject t) {
        LinearLayout box=vertical(); box.setPadding(dp(20),dp(8),dp(20),0);
        EditText title=input("Ne yapacaksın?",t == null ? "" : t.optString("title"),1);
        title.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(500)});
        EditText note=input("Not (isteğe bağlı)",t == null ? "" : t.optString("description"),2);
        note.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(20000)});
        box.addView(title); box.addView(note); box.addView(text("Öncelik",13,MUTED));
        Spinner priority=new Spinner(this);
        priority.setAdapter(new ArrayAdapter<String>(this,android.R.layout.simple_spinner_dropdown_item,new String[]{"Düşük","Normal","Yüksek"}));
        String current=t == null ? "medium" : t.optString("priority");
        priority.setSelection(current.equals("high") ? 2 : current.equals("low") ? 0 : 1); box.addView(priority);
        ScrollView scroll=new ScrollView(this); scroll.addView(box);
        AlertDialog.Builder builder=new AlertDialog.Builder(this).setTitle(t == null ? "Yeni görev" : "Görevi düzenle")
            .setView(scroll).setNegativeButton("Vazgeç",null).setPositiveButton("Kaydet",null);
        if(t != null) builder.setNeutralButton("Sil",(d,w) -> new AlertDialog.Builder(this).setTitle("Görev silinsin mi?")
            .setMessage(t.optString("title")).setNegativeButton("Vazgeç",null).setPositiveButton("Sil",(dd,ww) -> {
                store.delete(t.optString("uid")); render(); sync();
            }).show());
        AlertDialog dialog=builder.create(); dialog.show();
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            if(title.getText().toString().trim().isEmpty()) { title.setError("Bir görev başlığı yaz."); return; }
            store.edit(t == null ? null : t.optString("uid"),title.getText().toString(),note.getText().toString(),
                new String[]{"low","medium","high"}[priority.getSelectedItemPosition()],t == null ? "pending" : t.optString("status"),t == null ? 0 : t.optInt("version"));
            dialog.dismiss(); render(); sync();
        });
    }
    private String summary(JSONObject t) {
        if(t.optInt("deleted") == 1) return "Silinmiş";
        String status=t.optString("status"), priority=t.optString("priority");
        return t.optString("title")+"\n"+t.optString("description")+"\n"
            +(status.equals("done") ? "Tamamlandı" : status.equals("in_progress") ? "Devam ediyor" : status.equals("archived") ? "Arşivlendi" : "Bekliyor")
            +" · "+(priority.equals("high") ? "Yüksek" : priority.equals("low") ? "Düşük" : "Normal")+" öncelik";
    }
    private void conflict(JSONObject t) {
        new AlertDialog.Builder(this).setTitle("Hangi değişiklik kalsın?")
            .setMessage("Telefonda\n"+summary(t)+"\n\nBilgisayarda\n"+summary(t.optJSONObject("_conflict"))
                +"\n\nBilgisayarda silinmişse, telefon sürümü yeni görev olarak korunur.")
            .setNegativeButton("Sonra",null)
            .setNeutralButton("Bilgisayardaki",(d,w) -> { store.resolve(t.optString("uid"),false); render(); sync(); })
            .setPositiveButton("Telefondaki",(d,w) -> { store.resolve(t.optString("uid"),true); render(); sync(); }).show();
    }
    private void pair() {
        new AlertDialog.Builder(this).setTitle("Bilgisayarını bağla")
            .setMessage("Bilgisayardaki clar-focus-pairing.json dosyasını telefonuna aktar ve seç. İki cihaz aynı Wi-Fi ağına bağlı olsun.\n\nBilgisayar kapalıyken görev ekleyebilirsin; bağlantı gelince eşitlenir.")
            .setNegativeButton("Vazgeç",null).setPositiveButton("Dosyayı seç",(d,w) -> {
                Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT); intent.setType("*/*"); intent.addCategory(Intent.CATEGORY_OPENABLE);
                startActivityForResult(intent,10);
            }).show();
    }
    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if(request != 10 || result != RESULT_OK || data == null) return;
        try(InputStream in=getContentResolver().openInputStream(data.getData()); ByteArrayOutputStream out=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[1024]; int n;
            while((n=in.read(buffer)) != -1) { if(out.size()+n > 8192) throw new IOException("Eşleştirme dosyası çok büyük."); out.write(buffer,0,n); }
            store.pair(new String(out.toByteArray(),StandardCharsets.UTF_8)); render(); sync();
        } catch(Exception e) { new AlertDialog.Builder(this).setTitle("Eşleştirilemedi").setMessage(e.getMessage()).setPositiveButton("Tamam",null).show(); }
    }
}
