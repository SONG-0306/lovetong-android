import { CapacitorConfig } from '@capacitor/core';

const config: CapacitorConfig = {
  appId: 'com.lovetong.app',
  appName: 'lovetong',
  webDir: 'dist',
  server: {
    // 套壳外部网页：App 启动即加载该 URL（类似 Pake 的网页转应用）
    url: 'https://love-tong.pages.dev',
    cleartext: false,
  },
};

export default config;
