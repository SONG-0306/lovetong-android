#!/usr/bin/env python3
# 为 Capacitor 安卓工程打补丁：让被套壳网页里的 <input type=file> 在选择器里
# 同时出现「相册/文件」和「拍照」两个入口。
# 仅在 workflow 传入 enable_camera=true 时运行；每次 cap add 后重新执行，幂等。
import os
import re
import glob

ROOT = "android/app/src/main"
JAVA_ROOT = os.path.join(ROOT, "java")

main_files = glob.glob(os.path.join(JAVA_ROOT, "**", "MainActivity.java"), recursive=True)
if not main_files:
    raise SystemExit("找不到 MainActivity.java，请确认已执行 npx cap add android")
main_path = main_files[0]
main_dir = os.path.dirname(main_path)

with open(main_path, "r", encoding="utf-8") as f:
    main_src = f.read()

pkg_match = re.search(r"package\s+([\w.]+);", main_src)
if not pkg_match:
    raise SystemExit("无法解析 MainActivity 的 package")
pkg = pkg_match.group(1)

# ---- 1. 写自定义 WebChromeClient ----
client_path = os.path.join(main_dir, "CameraChromeClient.java")
client_src = '''package __PKG__;

import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.net.Uri;
import android.provider.MediaStore;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebView;

import androidx.appcompat.app.AlertDialog;

import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebChromeClient;

// 在网页文件选择器中加入「拍照」入口（继承 Capacitor 自带的 BridgeWebChromeClient，
// 保留其原有的定位/日志等行为，只扩展文件选择）。
// 用自己的 AlertDialog 选择「拍照 / 从相册选择」，比塞进系统选择器的
// EXTRA_INITIAL_INTENTS 在各机型上更可靠。
// 拍照输出到系统媒体库(MediaStore)的 Uri，这是 OEM 相机兼容性最好的方式。
public class CameraChromeClient extends BridgeWebChromeClient {
    private final Activity activity;
    private ValueCallback<Uri[]> uploadCallback;
    private Uri cameraOutputUri;
    private static final int REQ_CAMERA = 0xCAFE1;
    private static final int REQ_GALLERY = 0xCAFE2;

    public CameraChromeClient(Activity activity, Bridge bridge) {
        super(bridge);
        this.activity = activity;
    }

    @Override
    public boolean onShowFileChooser(WebView webView, ValueCallback<Uri[]> filePathCallback,
                                     FileChooserParams params) {
        this.uploadCallback = filePathCallback;

        String[] acceptTypes = (params != null) ? params.getAcceptTypes() : null;
        String mime = (acceptTypes != null && acceptTypes.length > 0 && acceptTypes[0] != null && !acceptTypes[0].isEmpty())
                ? acceptTypes[0] : "*/*";

        AlertDialog.Builder builder = new AlertDialog.Builder(activity);
        builder.setTitle("选择图片来源");
        builder.setItems(new String[]{"拍照", "从相册选择"}, (dialog, which) -> {
            if (which == 0) {
                openCamera();
            } else {
                openGallery(mime);
            }
        });
        // 取消（返回键 / 点对话框外）也要回调 null，否则网页的 file input 会卡住
        builder.setOnCancelListener(d -> finishWith(null));
        builder.show();
        return true;
    }

    private void openGallery(String mime) {
        try {
            Intent content = new Intent(Intent.ACTION_GET_CONTENT);
            content.addCategory(Intent.CATEGORY_OPENABLE);
            content.setType(mime);
            activity.startActivityForResult(content, REQ_GALLERY);
        } catch (Exception e) {
            finishWith(null);
        }
    }

    private void openCamera() {
        try {
            Intent capture = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            if (capture.resolveActivity(activity.getPackageManager()) == null) {
                // 设备没有相机应用，退回相册
                openGallery("image/*");
                return;
            }
            // 在媒体库建一个条目，把它的 Uri 作为拍照输出（兼容性最好）
            ContentValues values = new ContentValues();
            values.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
            values.put(MediaStore.Images.Media.DISPLAY_NAME, "IMG_" + System.currentTimeMillis() + ".jpg");
            cameraOutputUri = activity.getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
            if (cameraOutputUri == null) {
                openGallery("image/*");
                return;
            }
            capture.putExtra(MediaStore.EXTRA_OUTPUT, cameraOutputUri);
            activity.startActivityForResult(capture, REQ_CAMERA);
        } catch (Exception e) {
            // 任何异常都退回相册，避免闪退
            openGallery("image/*");
        }
    }

    private void finishWith(Uri[] results) {
        if (uploadCallback != null) {
            uploadCallback.onReceiveValue(results);
            uploadCallback = null;
        }
        cameraOutputUri = null;
    }

    public void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (uploadCallback == null) return;
        if (requestCode == REQ_CAMERA) {
            if (resultCode == Activity.RESULT_OK && cameraOutputUri != null) {
                finishWith(new Uri[]{cameraOutputUri});
            } else {
                finishWith(null);
            }
        } else if (requestCode == REQ_GALLERY) {
            if (resultCode == Activity.RESULT_OK && data != null && data.getData() != null) {
                finishWith(new Uri[]{data.getData()});
            } else {
                finishWith(null);
            }
        }
    }
}
'''.replace("__PKG__", pkg)

with open(client_path, "w", encoding="utf-8") as f:
    f.write(client_src)

# ---- 2. 改写 MainActivity，挂上自定义 client ----
if "CameraChromeClient" in main_src:
    print("[add-camera] MainActivity 已打过补丁，跳过。")
else:
    # 补 import
    if "import android.content.Intent;" not in main_src:
        main_src = main_src.replace(
            "import com.getcapacitor.BridgeActivity;",
            "import android.content.Intent;\nimport android.os.Bundle;\n\nimport com.getcapacitor.BridgeActivity;",
            1,
        )
    # 替换单行类声明为带成员的实现
    patched = main_src.replace(
        "public class MainActivity extends BridgeActivity {}",
        '''public class MainActivity extends BridgeActivity {
    private CameraChromeClient cameraChromeClient;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        cameraChromeClient = new CameraChromeClient(this, getBridge());
        getBridge().getWebView().setWebChromeClient(cameraChromeClient);
    }

    @Override
    public void onResume() {
        super.onResume();
        // 每次回到前台都确保自定义 client 仍生效（防止被框架覆盖）
        if (cameraChromeClient != null) {
            getBridge().getWebView().setWebChromeClient(cameraChromeClient);
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (cameraChromeClient != null) {
            cameraChromeClient.onActivityResult(requestCode, resultCode, data);
        }
        super.onActivityResult(requestCode, resultCode, data);
    }
}''',
        1,
    )
    if patched == main_src:
        raise SystemExit("未能替换 MainActivity 类声明，模板可能已变更。")
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(patched)
    print("[add-camera] 已为 MainActivity 注入相机支持。")

# ---- 3. 确保声明 CAMERA 权限（调用外部相机应用通常不需要，但部分机型更稳） ----
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
