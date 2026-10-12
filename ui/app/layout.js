import './globals.css';
import { AntdRegistry } from '@ant-design/nextjs-registry';

export const metadata = { title: '策略回测 · Quant', description: '选择策略，运行 Freqtrade 回测并查看结果' };

export default function RootLayout({ children }) {
  return <html lang="zh-CN"><body><AntdRegistry>{children}</AntdRegistry></body></html>;
}
