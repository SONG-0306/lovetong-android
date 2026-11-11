// 根据环境变量生成 capacitor.config.ts
// 这样同一个仓库可以按需打包任意网站，无需每个站一个仓库。
import { writeFileSync } from 'fs';

const siteUrl = (process.env.SITE_URL || 'https://love-tong.pages.dev').trim();
const appName = (process.env.APP_NAME || 'lovetong').trim();
const appIdInput = (process.env.APP_ID || '').trim();

// 包名必须唯一（否则同手机装不下两个）。未提供时按域名自动推导。
function deriveAppId(url, provided) {
  if (provided) return provided;
  try {
    const host = new URL(url).hostname.replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
    return `com.lovetong.${host}`;
  } catch {
    return 'com.lovetong.app';
  }
}

const appId = deriveAppId(siteUrl, appIdInput);
const cleartext = siteUrl.startsWith('http://'); // http 需开启 cleartext

const ts = `import { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: ${JSON.stringify(appId)},
  appName: ${JSON.stringify(appName)},
  webDir: 'dist',
  server: {
    // 套壳外部网页：App 启动即加载该 URL（类似 Pake 的网页转应用）
    url: ${JSON.stringify(siteUrl)},
    cleartext: ${cleartext},
  },
};

export default config;
`;

writeFileSync('capacitor.config.ts', ts);
console.log(`[gen-config] appName=${appName} appId=${appId} url=${siteUrl}`);
