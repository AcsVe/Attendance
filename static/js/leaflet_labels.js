/* نصوص أزرار الخريطة (Leaflet) بلغة الواجهة بدل الإنجليزية الافتراضية في المكتبة.
   الواجهة الإنجليزية تمر بالترجمة (i18n.js) فتُكتب هنا بالعربية. */
(function () {
  if (!window.L) return;
  L.Control.Zoom.prototype.options.zoomInTitle = 'تكبير';
  L.Control.Zoom.prototype.options.zoomOutTitle = 'تصغير';
  // رابط المكتبة في الزاوية بلا عبارة إنجليزية منبثقة
  L.Control.Attribution.prototype.options.prefix = '<a href="https://leafletjs.com" target="_blank" rel="noopener">Leaflet</a>';
  var onAdd = L.Control.Layers.prototype.onAdd;
  L.Control.Layers.prototype.onAdd = function (map) {
    var el = onAdd.call(this, map);
    var t = el.querySelector('.leaflet-control-layers-toggle');
    if (t) { t.title = 'نوع الخريطة'; t.setAttribute('aria-label', 'نوع الخريطة'); }
    return el;
  };
})();
