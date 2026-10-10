package dev.clar.focus;

import android.app.job.*;
import android.content.*;

/** Android controls background timing; foreground sync is immediate. */
public final class SyncJob extends JobService {
    public static void schedule(Context c) {
        JobScheduler scheduler=(JobScheduler)c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        scheduler.schedule(new JobInfo.Builder(42,new ComponentName(c,SyncJob.class))
            .setRequiredNetworkType(JobInfo.NETWORK_TYPE_UNMETERED)
            .setPeriodic(15*60*1000L).setPersisted(true).build());
    }
    @Override public boolean onStartJob(JobParameters params) {
        new Thread(() -> { Store.get(this).sync(); jobFinished(params,false); },"clar-background-sync").start();
        return true;
    }
    @Override public boolean onStopJob(JobParameters params) { return true; }
}
