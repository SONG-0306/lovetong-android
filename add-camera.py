#!/usr/bin/env python3
# 为 Capacitor 安卓工程打补丁：让被套壳网页里的 <input type=file accept=image/*>
# 点击时弹出「拍照 / 从相册选择」。
#   - 拍照：走 Capacitor Camera 官方插件（各机型兼容性最好，不依赖原生文件选择器）
#   - 相册：走系统选择器
# 仅在 workflow 传入 enable_camera=true 时运行；每次 cap add 后重新执行，幂等。
import os
import re
import glob

ROOT = "android/app/src/main"
JAVA_ROOT = os.path.join(ROOT, "java")

# 注入到网页的 JS：拦截图片 file input，提供「拍照/相册」选择。
HOOK_JS = r"""
(function () {
  if (window.__capCameraHook) return;
  window.__capCameraHook = true;

  function dataUrlToFile(dataUrl, filename) {
    var arr = dataUrl.split(',');
    var m = arr[0].match(/:(.*?);/);
    var mime = m ? m[1] : 'image/jpeg';
    var bstr = atob(arr[1]);
    var n = bstr.length;
    var u8 = new Uint8Array(n);
    while (n--) u8[n] = bstr.charCodeAt(n);
    return new File([u8], filename, { type: mime });
  }

  function setInputFiles(input, file) {
    var dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function takePhoto(input) {
    var C = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.Camera;
    if (!C) { input.click(); return; }
    C.getPhoto({
      source: 'CAMERA',
      resultType: 'DataUrl',
      saveToGallery: false,
      allowEditing: false
    }).then(function (res) {
      if (!res || !res.dataUrl) return;
      var file = dataUrlToFile(res.dataUrl, 'photo_' + Date.now() + '.jpg');
      setInputFiles(input, file);
    }).catch(function (err) {
      // 用户取消或出错：不处理
    });
  }

  var suppress = false;

  document.addEventListener('click', function (e) {
    if (suppress) { suppress = false; return; }
    var t = e.target;
    if (t && t.tagName === 'INPUT' && t.type === 'file') {
      var accept = (t.getAttribute('accept') || '').toLowerCase();
      if (accept.indexOf('image') === -1) return;
      e.preventDefault();
      e.stopPropagation();
      showChooser(t);
    }
  }, true);

  function showChooser(input) {
    var overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:2147483647;display:flex;align-items:center;justify-content:center;';
    overlay.addEventListener('click', function (ev) {
      if (ev.target === overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
    });
    var box = document.createElement('div');
    box.style.cssText = 'background:#fff;padding:20px;border-radius:14px;width:240px;max-width:80%;text-align:center;font-family:sans-serif;color:#222;box-shadow:0 8px 30px rgba(0,0,0,.3);';
    var title = document.createElement('div');
    title.textContent = '选择图片来源';
    title.style.cssText = 'font-size:16px;font-weight:600;margin-bottom:14px;';
    var bCam = document.createElement('button');
    bCam.textContent = '拍照';
    bCam.style.cssText = 'display:block;width:100%;padding:12px;margin-bottom:8px;border:none;border-radius:10px;background:#007aff;color:#fff;font-size:15px;';
    var bGal = document.createElement('button');
    bGal.textContent = '从相册选择';
    bGal.style.cssText = 'display:block;width:100%;padding:12px;border:none;border-radius:10px;background:#e9e9eb;color:#222;font-size:15px;';
    box.appendChild(title); box.appendChild(bCam); box.appendChild(bGal);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    function close() { if (overlay.parentNode) overlay.parentNode.removeChild(overlay); }
    bCam.onclick = function () { close(); takePhoto(input); };
    bGal.onclick = function () { close(); suppress = true; input.click(); };
  }
})();
"""

MAIN_BODY = '''public class MainActivity extends BridgeActivity {
    private boolean hookInjected = false;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
    }

    @Override
    public void onResume() {
        super.onResume();
        if (!hookInjected) {
            injectCameraHook();
            hookInjected = true;
        }
    }

    // 把 camera-hook.js 注入到网页，拦截图片上传框，加入拍照能力
    private void injectCameraHook() {
        try {
            java.io.InputStream is = getAssets().open("camera-hook.js");
            StringBuilder sb = new StringBuilder();
            java.io.BufferedReader br = new java.io.BufferedReader(new java.io.InputStreamReader(is, "UTF-8"));
            String line;
            while ((line = br.readLine()) != null) {
                sb.append(line).append("\\n");
            }
            br.close();
            WebView wv = getBridge().getWebView();
            wv.evaluateJavascript(sb.toString(), null);
        } catch (Exception e) {
            // 注入失败不影响网页本身使用
        }
    }
}'''


def main():
    main_files = glob.glob(os.path.join(JAVA_ROOT, "**", "MainActivity.java"), recursive=True)
    if not main_files:
        raise SystemExit("找不到 MainActivity.java，请确认已执行 npx cap add android")
    main_path = main_files[0]

    with open(main_path, "r", encoding="utf-8") as f:
        main_src = f.read()

    pkg_match = re.search(r"package\s+([\w.]+);", main_src)
    if not pkg_match:
        raise SystemExit("无法解析 MainActivity 的 package")
    pkg = pkg_match.group(1)

    # 1) 写入注入脚本到 assets
    assets_dir = os.path.join(ROOT, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    with open(os.path.join(assets_dir, "camera-hook.js"), "w", encoding="utf-8") as f:
        f.write(HOOK_JS)
    print("[add-camera] 已写入 camera-hook.js")

    # 2) 改写 MainActivity，在 onResume 注入脚本（直接按包名重写，兼容旧补丁版本）
    # 清理上一版遗留的 CameraChromeClient（已不再使用）
    for stale in glob.glob(os.path.join(JAVA_ROOT, "**", "CameraChromeClient.java"), recursive=True):
        try:
            os.remove(stale)
        except OSError:
            pass

    if "injectCameraHook" in main_src:
        print("[add-camera] MainActivity 已打过补丁，跳过。")
    else:
        desired = (
            "package " + pkg + ";\n\n"
            "import android.os.Bundle;\n"
            "import android.webkit.WebView;\n\n"
            "import com.getcapacitor.BridgeActivity;\n\n"
            + MAIN_BODY + "\n"
        )
        with open(main_path, "w", encoding="utf-8") as f:
            f.write(desired)
        print("[add-camera] 已为 MainActivity 注入相机脚本。")

    # 3) 确保声明 CAMERA 权限（Capacitor Camera 插件也会加，双保险）
    manifest_path = os.path.join(ROOT, "AndroidManifest.xml")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = f.read()
    if "android.permission.CAMERA" not in manifest:
        manifest = manifest.replace(
            '<uses-permission android:name="android.permission.INTERNET" />',
            '<uses-permission android:name="android.permission.INTERNET" />\n    <uses-permission android:name="android.permission.CAMERA" />',
            1,
        )
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(manifest)
        print("[add-camera] 已添加 CAMERA 权限声明。")

    print("[add-camera] 完成。package =", pkg)


if __name__ == "__main__":
    main()
