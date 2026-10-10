export function localPreviewEnabled(development: boolean, enabled: string | undefined, hostname: string, initData: string): boolean {
  return development && enabled === 'true'
    && ['localhost', '127.0.0.1'].includes(hostname) && !initData;
}
