import test from 'node:test';
import assert from 'node:assert/strict';
import { defaults, validateConfig, runnerArguments } from '../lib/config.mjs';

test('stoploss percent reaches native CLI and old records retain their original defaults',async()=>{
  const {restoreStoplossPercent}=await import('../lib/config.mjs');
  const c=validateConfig({...defaults,stoplossPercent:2.5}),a=runnerArguments(c,'/work/user_data/ui-runs/test');
  assert.equal(a[a.indexOf('--stoploss-percent')+1],'2.5');
  assert.equal(restoreStoplossPercent({strategies:['S03']}),5);
  assert.equal(restoreStoplossPercent({strategies:['S09']}),10);
  assert.equal(restoreStoplossPercent({strategies:['S03'],stoploss_percent:7.5}),7.5);
  for(const value of [0,-5,100,NaN,Infinity,null,'5'])
    assert.throws(()=>validateConfig({...defaults,stoplossPercent:value}));
  for(const value of [0.01,99.99]) assert.equal(validateConfig({...defaults,stoplossPercent:value}).stoplossPercent,value);
});

test('valid request yields fixed argv with selected strategies and native windows',()=>{
  const config=validateConfig({...defaults,strategies:['S01','S02'],fast:10,slow:80,skipDownload:true});
  const args=runnerArguments(config,'/work/user_data/ui-runs/test');
  assert.equal(args[args.indexOf('--fast')+1],'10');
  assert.equal(args[args.indexOf('--slow')+1],'80');
  assert.ok(!args.includes('--skip-download'));
  assert.ok(!('skipDownload' in config));
  assert.deepEqual(args.slice(args.indexOf('--strategies')+1,args.indexOf('--exchange')),['S01','S02']);
});
test('reject unknown strategies and shell/path injection inputs',()=>{
  for(const change of [{strategies:['../../evil']},{exchange:'binance; touch /tmp/x'},
    {pairs:['BTC/USDT;echo x']},{pairs:['../../USDT']},{pairs:['BTC/USDT:USDT']}])
    assert.throws(()=>validateConfig({...defaults,...change}));
});
test('reject invalid dates, numerical bounds and infeasible stake',()=>{
  for(const change of [{start:'2026-02-30'},{end:defaults.start},{fee:NaN},{stake:10000},
    {wallet:Infinity},{fast:60},{entry:2,exit:3},{slow:3.5}])
    assert.throws(()=>validateConfig({...defaults,...change}));
});
test('S05 must use daily candles and duplicate pairs/strategies are normalized',()=>{
  assert.throws(()=>validateConfig({...defaults,strategies:['S05'],timeframe:'1h'}));
  const config=validateConfig({...defaults,strategies:['S01','S01'],pairs:['BTC/USDT','BTC/USDT']});
  assert.deepEqual(config.strategies,['S01']);assert.deepEqual(config.pairs,['BTC/USDT']);
});

// MACD参数和细周期必须经后端校验并原样传入Freqtrade命令数组。
test('MACD configurable windows and detail timeframe reach native runner',()=>{
  const config=validateConfig({...defaults,macdFast:19,macdSlow:39,macdSignal:9});
  const args=runnerArguments(config,'/work/user_data/ui-runs/test');
  assert.equal(args[args.indexOf('--macd-fast')+1],'19');
  assert.equal(args[args.indexOf('--macd-slow')+1],'39');
  assert.equal(args[args.indexOf('--macd-signal')+1],'9');
  assert.equal(args[args.indexOf('--timeframe-detail')+1],'5m');
  for(const change of [{macdFast:26},{macdSignal:1},{macdFast:12.5},{timeframeDetail:'1m; echo x'}])
    assert.throws(()=>validateConfig({...defaults,...change}));
});

test('enhancement toggles default off and all options reach CLI as structured argv',()=>{
  const original=validateConfig(defaults);
  for(const key of ['macdMtf','macdRsi','macdMa','macdVolume']) assert.equal(original[key],false);
  assert.ok(!runnerArguments(original,'/work/user_data/ui-runs/test').includes('--macd-mtf'));
  const config=validateConfig({...defaults,timeframe:'1h',macdMtf:true,macdTrendTimeframe:'1d',
    macdTrendMode:'both',macdTrendFast:19,macdTrendSlow:39,macdRsi:true,macdRsiMin:0,
    macdRsiMax:65,macdMa:true,macdMaType:'sma',macdMaPeriod:100,macdVolume:true,
    macdVolumeWindow:30,macdVolumeMultiplier:1.5});
  const args=runnerArguments(config,'/work/user_data/ui-runs/test');
  for(const flag of ['--macd-mtf','--macd-rsi','--macd-ma','--macd-volume']) assert.ok(args.includes(flag));
  for(const [flag,value] of [['--macd-trend-mode','both'],['--macd-trend-fast','19'],
    ['--macd-rsi-min','0'],['--macd-rsi-max','65'],['--macd-ma-type','sma'],
    ['--macd-ma-period','100'],['--macd-volume-window','30'],['--macd-volume-multiplier','1.5']])
    assert.equal(args[args.indexOf(flag)+1],value);
});
test('enhancements reject invalid timeframe ordering, ranges, types and non-MACD use',()=>{
  for(const change of [{macdMtf:true},{timeframe:'4h',macdMtf:true,macdTrendTimeframe:'4h'},
    {macdRsiMin:70,macdRsiMax:30},{macdRsi:true,macdRsiPeriod:null},
    {macdTrendMode:'future'},{macdTrendTimeframe:'1m'},{macdTrendFast:26},
    {macdMaType:'weighted'},{macdVolumeMultiplier:0},{macdVolumeMultiplier:Infinity},
    {macdMtf:'false'},{strategies:['S01'],macdRsi:true}])
    assert.throws(()=>validateConfig({...defaults,...change}));
});
test('old/native records restore actual filter settings instead of inheriting new defaults',async()=>{
  const {restoreMacdOptions,macdFilterDescriptions}=await import('../lib/config.mjs');
  const old=restoreMacdOptions({});assert.equal(old.macdMtf,false);assert.deepEqual(macdFilterDescriptions({}),[]);
  const native={timeframe:'1h',macd_mtf:true,macd_trend_mode:'zero',macd_rsi:true,macd_rsi_max:65,macd_volume:true};
  const restored=restoreMacdOptions(native);
  assert.equal(restored.macdMtf,true);assert.equal(restored.macdRsiMax,65);
  assert.equal(restored.macdMa,false);assert.equal(macdFilterDescriptions(native).length,3);
});

test('S09 uses BTC cross signals only and trades ETH',async()=>{
  const {restoreBtcOptions}=await import('../lib/config.mjs');
  const input={...defaults,strategies:['S09'],pairs:['ETH/USDT'],timeframe:'1h',btcFast:19,btcSlow:39,btcMode:'cross',btcExit:true};
  const config=validateConfig(input),args=runnerArguments(config,'/work/user_data/ui-runs/test');
  assert.ok(!args.includes('--no-btc-exit'));assert.equal(args[args.indexOf('--btc-mode')+1],'cross');assert.equal(args[args.indexOf('--btc-fast')+1],'19');
  assert.equal(args[args.indexOf('--btc-timeframe')+1],'1d');
  assert.deepEqual(args.slice(args.indexOf('--pairs')+1,args.indexOf('--timeframe')),['ETH/USDT']);
  for(const change of [{pairs:['BTC/USDT']},{pairs:['ETH/USDT','BTC/USDT']},{timeframe:'1d',btcTimeframe:'4h'},
    {btcExit:'false'},{btcExit:false},{btcMode:'both'},{btcFast:null},{btcSlow:19},{btcMode:'foo'}])assert.throws(()=>validateConfig({...input,...change}));
  assert.equal(restoreBtcOptions({btc_exit:false,btc_fast:19}).btcExit,false);
});

test('BTC strategy choice and moving-average windows are persisted and reach native CLI',async()=>{
  const {restoreBtcOptions}=await import('../lib/config.mjs');
  const c=validateConfig({...defaults,strategies:['S09'],pairs:['ETH/USDT'],timeframe:'1h',btcStrategy:'sma',btcMaFast:50,btcMaSlow:200});
  const a=runnerArguments(c,'/work/user_data/ui-runs/test');
  assert.equal(a[a.indexOf('--btc-strategy')+1],'sma');assert.equal(a[a.indexOf('--btc-ma-fast')+1],'50');assert.equal(a[a.indexOf('--btc-ma-slow')+1],'200');
  assert.equal(restoreBtcOptions({}).btcStrategy,'macd');
  assert.equal(restoreBtcOptions({btc_strategy:'sma',btc_ma_fast:50}).btcMaFast,50);
  for(const patch of [{btcStrategy:'fake'},{btcMaFast:200},{btcMaSlow:2},{btcMaFast:null}])assert.throws(()=>validateConfig({...c,...patch}));
});
test('shared shortcut specifications include canonical MACD and custom detection',async()=>{
  const {MACD_PRESETS,MA_PRESETS,detectPreset}=await import('../lib/parameter-presets.mjs');
  assert.deepEqual(MACD_PRESETS.map(p=>p.values),[[6,12,9],[12,26,9],[19,39,9]]);
  assert.equal(detectPreset(MACD_PRESETS,[12,26,9]),'medium');assert.equal(detectPreset(MACD_PRESETS,[10,30,8]),'custom');
  assert.equal(detectPreset(MA_PRESETS,[20,60]),'medium');
  for(const p of MACD_PRESETS){const c=validateConfig({...defaults,strategies:['S09'],pairs:['ETH/USDT'],timeframe:'1h',btcFast:p.values[0],btcSlow:p.values[1],btcSignal:p.values[2]});assert.deepEqual([c.btcFast,c.btcSlow,c.btcSignal],p.values);}
});
