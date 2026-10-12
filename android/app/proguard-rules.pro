# واجهة الجافاسكربت يجب ألا تُحذف أو يُغيَّر اسمها
-keepclassmembers class org.iajaward.attendance.MainActivity$Bridge {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface
