// 浏览器提交的参数只转换为白名单参数数组；绝不拼接 shell 命令执行。
export const catalog = [
  {id:'S01', name:'双均线趋势', description:'短均线高于长均线时做多', kind:'趋势', timeframe:'日线起点'},
  {id:'S02', name:'唐奇安突破', description:'突破历史高点入场，跌破短通道退出', kind:'突破', timeframe:'日线起点'},
  {id:'S03', name:'布林带反弹', description:'下轨买入，中轨退出，最多持有20周期', kind:'回归', timeframe:'日线起点'},
  {id:'S04', name:'RSI 超卖回调', description:'RSI(2)超卖且处于长期上升趋势', kind:'回调', timeframe:'日线起点'},
  {id:'S05', name:'时间序列动量', description:'365日动量，UTC月末更新方向', kind:'动量', timeframe:'仅日线'},
  {id:'S09', name:'BTC 趋势交易 ETH', description:'BTC趋势允许时，ETH金叉买入；只交易ETH/USDT', kind:'跨资产', timeframe:'BTC日线 / ETH小时线'},
  {id:'S08', name:'MACD 金叉死叉', description:'DIF上穿DEA买入，下穿卖出，默认中线12/26/9', kind:'趋势', timeframe:'日线信号'},
];
// 原生命令行/审计字段与UI采用相同参数语义；旧记录缺字段时按全部关闭处理。
export const macdOptionDefaults = {macdMtf:false,macdTrendTimeframe:'1d',macdTrendMode:'dif_dea',
  macdTrendFast:12,macdTrendSlow:26,macdTrendSignal:9,macdRsi:false,macdRsiPeriod:14,
  macdRsiMin:30,macdRsiMax:70,macdMa:false,macdMaType:'ema',macdMaPeriod:200,
  macdVolume:false,macdVolumeWindow:20,macdVolumeMultiplier:1.2};
export function restoreMacdOptions(input) {
  return Object.fromEntries(Object.entries(macdOptionDefaults).map(([key,value])=>{
    const snake=key.replace(/[A-Z]/g,c=>'_'+c.toLowerCase());
    return [key,input[key]!==undefined?input[key]:input[snake]!==undefined?input[snake]:value];
  }));
}
export function macdFilterDescriptions(input) {
  const c=restoreMacdOptions(input),labels=[];
  if(c.macdMtf) labels.push(`多周期 ${c.macdTrendTimeframe}→${input.timeframe} · 长MACD ${c.macdTrendFast}/${c.macdTrendSlow}/${c.macdTrendSignal} · ${{dif_dea:'DIF>DEA',zero:'DIF>0',both:'DIF>DEA且DIF>0'}[c.macdTrendMode]}`);
  if(c.macdRsi) labels.push(`RSI(${c.macdRsiPeriod}) ${c.macdRsiMin}–${c.macdRsiMax}`);
  if(c.macdMa) labels.push(`收盘>${c.macdMaType.toUpperCase()}${c.macdMaPeriod}`);
  if(c.macdVolume) labels.push(`成交量≥此前${c.macdVolumeWindow}根均量×${c.macdVolumeMultiplier}`);
  return labels;
}
export const btcDefaults={btcTimeframe:'1d',btcMode:'both',btcFast:12,btcSlow:26,btcSignal:9,btcExit:true};
export function restoreBtcOptions(input) {return Object.fromEntries(Object.entries(btcDefaults).map(([key,value])=>{const snake=key.replace(/[A-Z]/g,c=>'_'+c.toLowerCase());return [key,input[key]!==undefined?input[key]:input[snake]!==undefined?input[snake]:value]}));}
export const defaults = { strategies:['S08'], exchange:'binance', pairs:['BTC/USDT'],
  timeframe:'1d', timeframeDetail:'5m', start:'2026-01-01', end:'2026-10-12', fee:0.001, wallet:10000,
  stake:1000, fast:20, slow:60, entry:20, exit:10, macdFast:12, macdSlow:26, macdSignal:9, ...macdOptionDefaults, ...btcDefaults, skipDownload:false };

function fail(message) { throw new Error(message); }
function numeric(input, name, low, high, integer=false) {
  const value=input[name];
  if(typeof value!=='number' || !Number.isFinite(value) || value<low || value>high || (integer&&!Number.isInteger(value))) fail(`${name}参数无效`);
  return value;
}
export function validateConfig(input) {
  if(!input || typeof input!=='object' || Array.isArray(input)) fail('回测参数无效');
  if(!Array.isArray(input.strategies) || input.strategies.length===0 || input.strategies.length>catalog.length ||
     input.strategies.some(s=>!catalog.some(c=>c.id===s))) fail('请选择已实现的策略');
  if(!['binance','okx','kraken'].includes(input.exchange)) fail('交易所不支持');
  if(!['1d','4h','1h'].includes(input.timeframe)) fail('周期不支持');
  if(!['5m',''].includes(input.timeframeDetail ?? '')) fail('成交细化周期不支持');
  if(input.strategies.includes('S05')&&input.timeframe!=='1d') fail('S05仅支持日线');
  if(!Array.isArray(input.pairs)||input.pairs.length<1||input.pairs.length>20||
     input.pairs.some(p=>typeof p!=='string'||!/^[-A-Z0-9]+\/USDT$/.test(p))) fail('请输入USDT现货交易对，如BTC/USDT');
  for(const key of ['start','end']) {
    const value=input[key];
    if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value)||!Number.isFinite(Date.parse(value))||new Date(value).toISOString().slice(0,10)!==value) fail('日期格式无效');
  }
  if(input.start>=input.end) fail('开始日期必须早于结束日期');
  const config={ strategies:[...new Set(input.strategies)], exchange:input.exchange,
    pairs:[...new Set(input.pairs)], timeframe:input.timeframe, start:input.start,end:input.end,
    fee:numeric(input,'fee',0,0.099), wallet:numeric(input,'wallet',1,1e12),
    stake:numeric(input,'stake',1,1e12), fast:numeric(input,'fast',2,399,true),
    slow:numeric(input,'slow',3,400,true),entry:numeric(input,'entry',2,400,true),
    exit:numeric(input,'exit',1,400,true),skipDownload:input.skipDownload===true,
    timeframeDetail:input.timeframeDetail ?? '',
    macdFast:numeric({...input,macdFast:input.macdFast??12},'macdFast',2,399,true),
    macdSlow:numeric({...input,macdSlow:input.macdSlow??26},'macdSlow',3,400,true),
    macdSignal:numeric({...input,macdSignal:input.macdSignal??9},'macdSignal',2,100,true) };
  const options=restoreMacdOptions(input);
  for(const key of ['macdMtf','macdRsi','macdMa','macdVolume']) {
    if(typeof options[key]!=='boolean') fail('增强开关必须为布尔值');
    config[key]=options[key];
  }
  for(const [key,choices] of [['macdTrendTimeframe',['4h','1d']],['macdTrendMode',['dif_dea','zero','both']],['macdMaType',['ema','sma']]]) {
    if(!choices.includes(options[key])) fail(`${key}参数无效`);
    config[key]=options[key];
  }
  for(const [key,low,high] of [['macdTrendFast',2,399],['macdTrendSlow',3,400],['macdTrendSignal',2,100],
    ['macdRsiPeriod',2,100],['macdRsiMin',0,99],['macdRsiMax',1,100],['macdMaPeriod',2,400],['macdVolumeWindow',2,400]])
    config[key]=numeric(options,key,low,high,true);
  config.macdVolumeMultiplier=numeric(options,'macdVolumeMultiplier',0.1,10);
  if(config.macdTrendFast>=config.macdTrendSlow) fail('长周期MACD快线必须小于慢线');
  if(config.macdRsiMin>=config.macdRsiMax) fail('RSI下限必须小于上限');
  if(['macdMtf','macdRsi','macdMa','macdVolume'].some(key=>config[key])&&!config.strategies.includes('S08')) fail('增强选项只适用于S08 MACD');
  const minutes={'1h':60,'4h':240,'1d':1440};
  if(config.macdMtf&&minutes[config.macdTrendTimeframe]<=minutes[config.timeframe]) fail('趋势周期必须长于入场信号周期');
  const btc=restoreBtcOptions(input);
  if(!['4h','1d'].includes(btc.btcTimeframe)||!['dif_dea','zero','both'].includes(btc.btcMode)||typeof btc.btcExit!=='boolean') fail('BTC趋势参数无效');
  Object.assign(config,{btcTimeframe:btc.btcTimeframe,btcMode:btc.btcMode,btcExit:btc.btcExit});
  for(const [key,low,high] of [['btcFast',2,399],['btcSlow',3,400],['btcSignal',2,100]]) config[key]=numeric(btc,key,low,high,true);
  if(config.btcFast>=config.btcSlow) fail('BTC快线必须小于慢线');
  if(config.strategies.includes('S09')) {
    if(config.pairs.length!==1||config.pairs[0]!=='ETH/USDT') fail('S09只交易ETH/USDT；BTC仅用于趋势参考');
    if(minutes[config.btcTimeframe]<minutes[config.timeframe]) fail('BTC趋势周期不能短于ETH入场周期');
  }
  if(config.stake>config.wallet*.99) fail('单笔投入不能超过初始资金的99%');
  if(config.fast>=config.slow) fail('短均线必须小于长均线');
  if(config.exit>config.entry) fail('退出窗口不能大于入场窗口');
  if(config.macdFast>=config.macdSlow) fail('MACD快线必须小于慢线');
  return config;
}
export function runnerArguments(config, outputDir) {
  const result=['run','--no-sync','python','scripts/run_backtest.py','--strategies',...config.strategies,
    '--exchange',config.exchange,'--pairs',...config.pairs,'--timeframe',config.timeframe,
    '--start',config.start,'--end',config.end,'--output-dir',outputDir];
  for(const name of ['fee','wallet','stake','fast','slow','entry','exit']) result.push(`--${name}`,String(config[name]));
  for(const [flag,key] of [['macd-fast','macdFast'],['macd-slow','macdSlow'],['macd-signal','macdSignal']]) result.push(`--${flag}`,String(config[key]));
  for(const key of ['macdMtf','macdRsi','macdMa','macdVolume'])
    if(config[key]) result.push('--'+key.replace(/[A-Z]/g,c=>'-'+c.toLowerCase()));
  for(const key of Object.keys(macdOptionDefaults).filter(key=>!['macdMtf','macdRsi','macdMa','macdVolume'].includes(key)))
    result.push('--'+key.replace(/[A-Z]/g,c=>'-'+c.toLowerCase()),String(config[key]??macdOptionDefaults[key]));
  if(config.strategies.includes('S09')) {
    for(const key of ['btcTimeframe','btcMode','btcFast','btcSlow','btcSignal']) result.push('--'+key.replace(/[A-Z]/g,c=>'-'+c.toLowerCase()),String(config[key]));
    result.push(config.btcExit?'--btc-exit':'--no-btc-exit');
  }
  if(config.timeframeDetail) result.push('--timeframe-detail',config.timeframeDetail);
  if(config.skipDownload) result.push('--skip-download');
  return result;
}
