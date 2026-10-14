package com.hdagent.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.view.Window;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

/** HD Agent — a thin, secure WebView shell around the HD Agent web app. */
public class MainActivity extends Activity {
    private static final int FILE_REQUEST = 41;
    private WebView web;
    private ValueCallback<Uri[]> fileCallback;
    private String appUrl;
    private String appHost;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        appUrl = getString(R.string.app_url);
        appHost = Uri.parse(appUrl).getHost();
        Window w = getWindow();
        w.setStatusBarColor(Color.parseColor("#123524"));

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#EEF4F0"));
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(true);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setUserAgentString(s.getUserAgentString() + " HDAgentApp/1");

        web.addJavascriptInterface(new Bridge(this), "HDAndroid");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (appHost != null && appHost.equals(u.getHost())) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, u));
                } catch (Exception ignored) {
                }
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) {
                    view.loadDataWithBaseURL(null, offlinePage(), "text/html", "utf-8", null);
                }
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams params) {
                if (fileCallback != null) {
                    fileCallback.onReceiveValue(null);
                }
                fileCallback = cb;
                Intent i = new Intent(Intent.ACTION_GET_CONTENT);
                i.addCategory(Intent.CATEGORY_OPENABLE);
                i.setType("image/*");
                try {
                    startActivityForResult(Intent.createChooser(i, "صورة التحويل"), FILE_REQUEST);
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });
        if (state != null) {
            web.restoreState(state);
        } else {
            web.loadUrl(appUrl);
        }
    }

    private String offlinePage() {
        return "<html dir='rtl'><body style='font-family:sans-serif;background:#EEF4F0;color:#16211B;display:flex;"
                + "flex-direction:column;align-items:center;justify-content:center;height:90vh;text-align:center'>"
                + "<h2>لا يوجد اتصال</h2><p>تأكد من الإنترنت ثم حاول مرة أخرى.</p>"
                + "<button style='background:#F2C14E;border:0;border-radius:14px;padding:14px 28px;font-size:16px' "
                + "onclick=\"location.href='" + appUrl + "'\">إعادة المحاولة</button></body></html>";
    }

    @Override
    protected void onActivityResult(int req, int result, Intent data) {
        super.onActivityResult(req, result, data);
        if (req == FILE_REQUEST && fileCallback != null) {
            Uri[] res = null;
            if (result == RESULT_OK && data != null && data.getData() != null) {
                res = new Uri[]{data.getData()};
            }
            fileCallback.onReceiveValue(res);
            fileCallback = null;
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    /** Exposed to the web app as window.HDAndroid (only our own site is ever loaded). */
    static class Bridge {
        private final Context ctx;

        Bridge(Context c) {
            ctx = c.getApplicationContext();
        }

        @JavascriptInterface
        public String deviceId() {
            String id = Settings.Secure.getString(ctx.getContentResolver(), Settings.Secure.ANDROID_ID);
            return id == null ? "" : id;
        }

        @JavascriptInterface
        public String deviceName() {
            return (Build.MANUFACTURER + " " + Build.MODEL).trim();
        }

        @JavascriptInterface
        public void copy(String text) {
            ClipboardManager cm = (ClipboardManager) ctx.getSystemService(Context.CLIPBOARD_SERVICE);
            if (cm != null) {
                cm.setPrimaryClip(ClipData.newPlainText("HD Agent", text));
            }
        }
    }
}
