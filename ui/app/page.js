'use client';
import { useEffect, useState } from 'react';
import { Alert, Badge, Button, Card, Checkbox, Collapse, ConfigProvider, Empty, Form, Input, InputNumber, Menu, Select, Skeleton, Spin, Switch, Table, Tag } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { ArrowLeftOutlined, ArrowRightOutlined, CheckCircleOutlined, ClockCircleOutlined, DatabaseOutlined, ExperimentOutlined, HistoryOutlined, PlayCircleOutlined, ReloadOutlined, SearchOutlined, SlidersOutlined } from '@ant-design/icons';
import { catalog, defaults, validateConfig, restoreMacdOptions, macdFilterDescriptions, restoreBtcOptions } from '../lib/config.mjs';

const statusNames={queued:'等待启动',running:'回测中',completed:'已完成',failed:'失败'};
const names=Object.fromEntries(catalog.map(s=>[s.id,s.name]));
const percent=value=>value==null?'—':`${(value*100).toFixed(2)}%`;
const money=value=>value==null?'—':Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
const localTime=value=>new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
const busy=job=>['queued','running'].includes(job?.status);
const presets={short:[6,12,9],medium:[12,26,9],long:[19,39,9]};
const theme={token:{colorPrimary:'#4965e8',colorSuccess:'#16866c',colorError:'#cb5360',colorText:'#243049',colorTextSecondary:'#8290a5',colorBorder:'#e1e6ef',colorBgLayout:'#f5f7fb',borderRadius:9,fontFamily:'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',controlHeight:42,fontSize:13},components:{Menu:{itemHeight:46,itemSelectedBg:'#eef1ff',itemSelectedColor:'#4965e8',itemBorderRadius:9},Card:{paddingLG:26},Table:{headerBg:'#f8f9fc',cellPaddingBlock:18}}};
async function api(url,options) {const response=await fetch(url,{cache:'no-store',...options});const body=await response.json();if(!response.ok)throw new Error(body.error||'请求失败');return body;}
function Status({status}) {return <Tag bordered={false} color={status==='completed'?'success':status==='failed'?'error':busy({status})?'processing':'default'}>{statusNames[status]||status}</Tag>}
function Metric({label,value,positive}) {return <div className="metric"><span>{label}</span><strong className={positive===undefined?'':positive?'positive':'negative'}>{value}</strong></div>}
function Field({label,id,children,wide=false}) {return <Form.Item label={label} htmlFor={id} className={wide?'wide':''}>{children}</Form.Item>}

function Enhancement({label,description,enabled,onChange,children}) {
  return <div className={`enhancement ${enabled?'enabled':''}`}><div className="enhancement-heading"><div><strong>{label}</strong><p>{description}</p></div><Switch checked={enabled} onChange={onChange} aria-label={`启用${label}`}/></div>{enabled&&<div className="enhancement-fields">{children}</div>}</div>;
}

const tradeTime=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'UTC',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'—';
const tradeDateCell=value=>value?<div>{tradeTime(value).split(' ')[0]}<span className="trade-secondary">{tradeTime(value).split(' ')[1]}</span></div>:'—';
const rate=value=>value==null?'—':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:8});
const reasons={macd_death_cross:'MACD 死叉',stop_loss:'固定止损',force_exit:'回测结束强制退出',exit_signal:'策略退出信号',roi:'ROI 止盈',trailing_stop_loss:'移动止损',sma_down:'均线转弱',channel_exit:'跌破通道',return_to_mean:'回到布林中轨',rsi_or_trend_exit:'RSI 或趋势退出',nonpositive_monthly_momentum:'月末动量转弱',hold_timeout:'持仓超时',btc_macd_death_cross:'BTC MACD 死叉',btc_trend_lost:'BTC 趋势转弱',eth_macd_death_cross:'ETH MACD 死叉'};
function Trades({entries}) {
  const missing=entries.some(([,s])=>!Array.isArray(s.trades));
  const rows=entries.flatMap(([strategy,s])=>(s.trades||[]).map((t,i)=>({...t,strategy,key:`${strategy}-${i}`}))).sort((a,b)=>(a.open_timestamp??Date.parse(a.open_date))-(b.open_timestamp??Date.parse(b.open_date)));
  const duration=minutes=>minutes==null?'—':`${Math.floor(minutes/1440)?`${Math.floor(minutes/1440)}天 `:''}${Math.floor(minutes%1440/60)}小时${minutes%60?` ${minutes%60}分`:''}`;
  const columns=[
    {title:'交易对 / 方向',dataIndex:'pair',width:105,render:(pair,t)=><div><strong>{pair}</strong><span className="trade-secondary">{entries.length>1?`${t.strategy.slice(0,3)} · `:''}{t.is_short?'做空':'做多'}</span></div>},
    {title:'入场时间 · UTC',dataIndex:'open_date',width:120,render:tradeDateCell,sorter:(a,b)=>a.open_timestamp-b.open_timestamp},
    {title:'退出时间 · UTC',dataIndex:'close_date',width:120,render:(value,t)=>t.is_open?'未平仓':tradeDateCell(value)},
    {title:'入场价格',dataIndex:'open_rate',align:'right',width:95,render:rate},
    {title:'退出价格',dataIndex:'close_rate',align:'right',width:95,render:rate},
    {title:'收益率',dataIndex:'profit_ratio',align:'right',width:85,sorter:(a,b)=>a.profit_ratio-b.profit_ratio,render:value=><span className={value>=0?'positive':'negative'}>{percent(value)}</span>},
    {title:'收益 · USDT',dataIndex:'profit_abs',align:'right',width:100,sorter:(a,b)=>a.profit_abs-b.profit_abs,render:value=><span className={value>=0?'positive':'negative'}>{money(value)}</span>},
    {title:'退出原因',dataIndex:'exit_reason',width:130,render:value=><span title={value}>{reasons[value]||value||'—'}</span>}
  ];
  return <section className="trade-section"><div className="trade-heading"><h3>交易记录 <span>{rows.length} 笔</span></h3><p>实际成交时间按 UTC 显示，逐笔收益来自 Freqtrade，已计入手续费。</p></div>
    {missing?<Alert type="warning" showIcon title="此记录缺少逐笔交易数据" description="原始导出文件不可用时，无法恢复交易明细。"/>:<Table className="trade-table" rowKey="key" size="small" columns={columns} dataSource={rows} scroll={{x:900}} pagination={{pageSize:10,showSizeChanger:false,hideOnSinglePage:true,showTotal:total=>`共 ${total} 笔交易`}} locale={{emptyText:<Empty description="此区间内没有交易"/>}} expandable={{expandedRowRender:t=><div className="trade-expanded"><span>投入：{money(t.stake_amount)} USDT</span><span>成交数量：{rate(t.amount)}</span><span>持仓时长：{duration(t.trade_duration)}</span><span>入场信号：{t.enter_tag||'—'}</span><span>退出标记：{t.exit_reason||'—'}</span><span>入场 / 退出费率：{percent(t.fee_open)} / {percent(t.fee_close)}</span></div>}}/>}
  </section>;
}

function Results({detail,loading,error}) {
  if(error)return <Alert type="error" showIcon title="读取结果失败" description={error}/>;
  if(loading)return <Card className="result-card"><Skeleton active paragraph={{rows:4}}/></Card>;
  if(!detail)return null;
  const {job,result,logs}=detail;
  const c=job.config;
  const stats=result?.strategies;
  const entries=Object.entries(stats||{});
  const single=entries.length===1?entries[0][1]:null;
  return <Card className="result-card" title={<span className="card-title">{busy(job)?'运行进度':'测试结果'}</span>} extra={<Status status={job.status}/>}>
    <div className="result-heading"><div><h3>{c.strategies.map(s=>`${s} · ${names[s]}`).join(' / ')}</h3><p>{c.exchange.toUpperCase()} · {c.pairs.join(' / ')} · {c.start} — {c.end}</p></div><span className="result-date">{localTime(job.createdAt)}</span></div>
    <div className="context-tags"><Tag>{c.strategies.includes('S09')?'ETH执行':'信号'} {c.timeframe}</Tag><Tag>成交 {c.timeframeDetail||c.timeframe_detail||c.timeframe}</Tag>{c.strategies.includes('S08')&&<Tag>MACD {c.macdFast??c.macd_fast??12} / {c.macdSlow??c.macd_slow??26} / {c.macdSignal??c.macd_signal??9}</Tag>}<Tag>手续费 {percent(c.fee)}</Tag></div>
    {c.strategies.includes('S08')&&<div className="filter-tags">{macdFilterDescriptions(c).length?macdFilterDescriptions(c).map(label=><Tag key={label}>{label}</Tag>):<span>增强选项全部关闭 · 基础MACD</span>}</div>}
    {c.strategies.includes('S09')&&<div className="filter-tags"><Tag>BTC/USDT {restoreBtcOptions(c).btcTimeframe} · MACD {restoreBtcOptions(c).btcFast}/{restoreBtcOptions(c).btcSlow}/{restoreBtcOptions(c).btcSignal}</Tag>{restoreBtcOptions(c).btcMode==='cross'?<Tag>BTC金叉买ETH · BTC死叉卖ETH</Tag>:<><Tag>旧规则：BTC过滤＋ETH MACD</Tag><Tag>ETH MACD {c.macdFast??c.macd_fast??12}/{c.macdSlow??c.macd_slow??26}/{c.macdSignal??c.macd_signal??9}</Tag><Tag>BTC转弱退出：{restoreBtcOptions(c).btcExit?'开启':'关闭'}</Tag></>}</div>}
    {busy(job)?<div className="running-state"><Spin/><div><strong>正在执行回测</strong><p>准备行情、计算信号并模拟成交，完成后自动显示结果。</p></div></div>:job.status==='failed'?<Alert type="error" showIcon title="本次回测未完成" description={job.error||'请展开运行日志查看原因。'}/>:stats?<>
      {single&&<div className="metrics"><Metric label="总资金收益率" value={percent(single.profit_total)} positive={single.profit_total>=0}/><Metric label="收益 · USDT" value={money(single.profit_total_abs)} positive={single.profit_total_abs>=0}/><Metric label="最大回撤" value={percent(single.max_drawdown_account)}/><Metric label="交易次数 / 胜率" value={`${single.total_trades} / ${percent(single.winrate)}`}/></div>}
      {!single&&<Table size="small" pagination={false} scroll={{x:700}} rowKey="name" dataSource={entries.map(([name,s])=>({...s,name}))} columns={[{title:'策略',dataIndex:'name',render:name=>names[name.slice(0,3)]||name},{title:'交易数',dataIndex:'total_trades',align:'right'},{title:'总资金收益率',dataIndex:'profit_total',align:'right',render:percent},{title:'收益 USDT',dataIndex:'profit_total_abs',align:'right',render:money},{title:'最大回撤',dataIndex:'max_drawdown_account',align:'right',render:percent},{title:'胜率',dataIndex:'winrate',align:'right',render:percent}]}/>}
      <Trades entries={entries}/>
      <div className="result-footnote"><CheckCircleOutlined/> 已完成 · 初始 {money(c.wallet)} / 每笔 {money(c.stake)} USDT<span>UTC 区间，终点不含 · 回撤按已平仓余额统计 · 未另加滑点模型</span></div>
    </>:<Empty description="结果文件尚未生成"/>}
    <Collapse className="result-details" ghost items={[{key:'parameters',label:'实际运行参数',children:<pre className="parameter-json">{JSON.stringify(result?.run?.arguments||c,null,2)}</pre>},{key:'logs',label:'运行日志',children:<pre className="log-output">{logs||'等待日志…'}</pre>}]}/>
  </Card>;
}

export default function Dashboard() {
  const [view,setView]=useState('run');
  const [historyId,setHistoryId]=useState(null);
  const [runId,setRunId]=useState(null);
  const [config,setConfig]=useState({...defaults});
  const [preset,setPreset]=useState('medium');
  const [pairText,setPairText]=useState('BTC/USDT');
  const [feeText,setFeeText]=useState(0.1);
  const [jobs,setJobs]=useState([]);
  const [detail,setDetail]=useState(null);
  const [detailError,setDetailError]=useState('');
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [submitting,setSubmitting]=useState(false);
  const [ready,setReady]=useState(false);
  const [query,setQuery]=useState('');
  const [statusFilter,setStatusFilter]=useState('all');
  const selected=view==='run'?runId:historyId;
  const active=jobs.find(busy);
  const strategy=catalog.find(s=>s.id===config.strategies[0]);
  async function loadJobs() {const data=await api('/api/backtests');setJobs(data.jobs);setReady(true);return data.jobs;}
  function navigate(next,id=null) {window.location.hash=next==='history'&&id?`history/${id}`:next;}
  // 菜单与详情状态写入URL；浏览器后退和刷新保持当前历史详情。
  useEffect(()=>{
    const sync=()=>{const [page,id]=window.location.hash.slice(1).split('/');setView(page==='history'?'history':'run');setHistoryId(page==='history'&&id?id:null)};
    sync();window.addEventListener('hashchange',sync);
    let cancelled=false;
    loadJobs().then(list=>{if(cancelled)return;const saved=sessionStorage.getItem('quant-current-run');const current=list.find(busy)||list.find(j=>j.id===saved);if(current)setRunId(current.id)}).catch(e=>{if(!cancelled)setError(e.message)});
    return()=>{cancelled=true;window.removeEventListener('hashchange',sync)};
  },[]);
  // 运行页只读取本次任务；历史页只读取点击的记录，防止旧结果冒充本次测试。
  useEffect(()=>{
    let cancelled=false;let timer;
    setDetail(null);setDetailError('');setLoading(!!selected);
    if(!selected)return;
    async function refresh() {
      try {
        const data=await api(`/api/backtests/${encodeURIComponent(selected)}`);
        if(cancelled)return;
        setDetail(data);setLoading(false);
        if(busy(data.job))timer=setTimeout(refresh,1800);
        else await loadJobs();
      }catch(e){if(!cancelled){setDetailError(e.message);setLoading(false)}}
    }
    refresh();return()=>{cancelled=true;clearTimeout(timer)};
  },[selected]);
  useEffect(()=>{if(!active)return;const timer=setInterval(()=>loadJobs().catch(e=>setError(e.message)),2500);return()=>clearInterval(timer)},[active?.id]);
  const set=(key,value)=>setConfig(old=>({...old,[key]:value}));
  function chooseStrategy(id) {setConfig(old=>({...old,strategies:[id],timeframe:id==='S05'?'1d':id==='S09'?'1h':old.timeframe,...(id==='S09'?{btcMode:'cross',btcExit:true}:{}),...(id!=='S08'?{macdMtf:false,macdRsi:false,macdMa:false,macdVolume:false}:{})}));if(id==='S09')setPairText('ETH/USDT');setError('')}
  function toggleMtf(value) {setConfig(old=>({...old,macdMtf:value,timeframe:value&&(old.timeframe==='1d'||old.timeframe===old.macdTrendTimeframe)?'1h':old.timeframe}))}
  function setMacd(key,value) {set(key,value);setPreset('custom')}
  function choosePreset(value) {setPreset(value);const p=presets[value];if(p)setConfig(old=>({...old,macdFast:p[0],macdSlow:p[1],macdSignal:p[2]}))}
  async function run() {
    setError('');setSubmitting(true);
    try {
      const payload=validateConfig({...config,pairs:pairText.trim().toUpperCase().split(/\s+/).filter(Boolean),fee:Number(feeText)/100});
      const data=await api('/api/backtests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      sessionStorage.setItem('quant-current-run',data.job.id);setRunId(data.job.id);setJobs(old=>[data.job,...old]);
    }catch(e){setError(e.message)}finally{setSubmitting(false)}
  }
  function reuse(c) {
    const next={...defaults,...c,...restoreMacdOptions(c),...restoreBtcOptions(c),strategies:[c.strategies[0]],timeframeDetail:c.timeframeDetail??c.timeframe_detail??'',macdFast:c.macdFast??c.macd_fast??12,macdSlow:c.macdSlow??c.macd_slow??26,macdSignal:c.macdSignal??c.macd_signal??9,skipDownload:c.skipDownload??c.skip_download??false};
    if(next.strategies[0]==='S09'){next.btcMode='cross';next.btcExit=true;}
    setConfig(next);setPairText(next.pairs.join(' '));setFeeText(next.fee*100);
    setPreset(Object.entries(presets).find(([,p])=>p[0]===next.macdFast&&p[1]===next.macdSlow&&p[2]===next.macdSignal)?.[0]||'custom');
    if(!active){setRunId(null);sessionStorage.removeItem('quant-current-run')}
    setError('');navigate('run');
  }
  const filtered=jobs.filter(job=>(statusFilter==='all'||job.status===statusFilter)&&`${job.config.strategies.map(s=>`${s} ${names[s]}`).join(' ')} ${job.config.pairs.join(' ')} ${job.config.start} ${job.config.end}`.toLowerCase().includes(query.toLowerCase()));
  const number=(key,label,min,max)=><Field label={label} id={key}><InputNumber id={key} min={min} max={max} precision={0} value={config[key]} onChange={value=>set(key,value)} controls={false}/></Field>;
  const columns=[{title:'策略 / 交易对',key:'strategy',render:(_,job)=><button className="record-link" onClick={()=>navigate('history',job.id)}><strong>{job.config.strategies.map(s=>names[s]).join(' + ')}</strong><span>{job.config.strategies.join(' + ')} · {job.config.pairs.join(' / ')}</span></button>},{title:'测试区间 · UTC',key:'range',render:(_,job)=><div className="record-range">{job.config.start}<span>至 {job.config.end}</span></div>},{title:'信号 / 成交',key:'timeframe',render:(_,job)=><span className="mono">{job.config.timeframe} / {job.config.timeframeDetail||job.config.timeframe_detail||job.config.timeframe}</span>},{title:'状态',dataIndex:'status',render:status=><Status status={status}/>},{title:'运行时间',dataIndex:'createdAt',render:value=><span className="record-time">{localTime(value)}</span>},{title:'',key:'action',render:(_,job)=><Button type="text" aria-label={`查看 ${job.config.strategies.join('+')} ${localTime(job.createdAt)} 的回测结果`} icon={<ArrowRightOutlined/>} onClick={()=>navigate('history',job.id)}/>}];
  return <ConfigProvider theme={theme} locale={zhCN}>
    <div className="app-shell">
      <aside className="sidebar"><a className="brand" href="#run"><span className="brand-mark"><ExperimentOutlined/></span><span>Quant<span className="brand-caption">策略研究工作台</span></span></a><div className="nav-caption">工作空间</div>
        <Menu selectedKeys={[view]} mode="inline" onClick={({key})=>navigate(key)} items={[{key:'run',icon:<PlayCircleOutlined/>,label:'运行回测'},{key:'history',icon:<HistoryOutlined/>,label:'历史回测'}]}/>
        <div className="sidebar-bottom"><Badge status="success" text="本地回测环境"/><span>Freqtrade · 离线研究</span></div>
      </aside>
      <div className="main-area"><header className="topbar"><span>工作空间 <span className="breadcrumb-separator">/</span> <strong>{view==='run'?'运行回测':'历史回测'}</strong></span><Tag icon={<DatabaseOutlined/>} bordered={false}>现货研究</Tag></header>
        <main className="page-content"><div className="page-heading"><div><span className="eyebrow">{view==='run'?'BACKTEST LAB':'BACKTEST HISTORY'}</span><h1>{view==='run'?'运行回测':historyId?'历史测试结果':'历史回测'}</h1><p>{view==='run'?'选择一个策略，设定参数，让数据检验你的想法。':historyId?'查看这次运行的参数、结果和日志。':'每一次测试都有记录，随时回看与复核。'}</p></div>{view==='history'&&!historyId&&<Button icon={<ReloadOutlined/>} onClick={()=>loadJobs().catch(e=>setError(e.message))}>刷新记录</Button>}</div>
          {view==='run'?<>
            <div className="run-layout"><Card className="form-card" title={<span className="card-title"><SlidersOutlined/> 回测设置</span>}><Form layout="vertical" onFinish={run} disabled={submitting||!!active}>
              <Field label="选择策略" id="strategy"><Select id="strategy" value={config.strategies[0]} onChange={chooseStrategy} options={catalog.map(s=>({value:s.id,label:`${s.id} · ${s.name}`}))}/></Field>
              <div className="strategy-description"><Tag bordered={false} color="blue">{strategy?.kind}</Tag><span>{strategy?.description}</span></div>
              <div className="form-divider"><span>市场与区间</span></div><div className="form-grid">
                <Field label="交易所" id="exchange"><Select id="exchange" value={config.exchange} onChange={value=>set('exchange',value)} options={['binance','okx','kraken'].map(value=>({value,label:{binance:'Binance',okx:'OKX',kraken:'Kraken'}[value]}))}/></Field>
                <Field label="交易对" id="pairs"><Input id="pairs" disabled={config.strategies[0]==='S09'||submitting||!!active} value={pairText} onChange={e=>setPairText(e.target.value)} placeholder="BTC/USDT"/></Field>
                <Field label="开始日期 · UTC" id="start"><Input id="start" type="date" value={config.start} onChange={e=>set('start',e.target.value)}/></Field>
                <Field label="结束日期 · 不含当日" id="end"><Input id="end" type="date" value={config.end} onChange={e=>set('end',e.target.value)}/></Field>
                <Field label={config.strategies[0]==='S09'?'ETH 执行周期':config.strategies[0]==='S08'&&config.macdMtf?'短周期入场信号':'信号周期'} id="timeframe"><Select id="timeframe" value={config.timeframe} onChange={value=>set('timeframe',value)} options={[{value:'1d',label:'日线 · 1d',disabled:(config.strategies[0]==='S08'&&config.macdMtf)||(config.strategies[0]==='S09'&&config.btcTimeframe!=='1d')},{value:'4h',label:'4 小时 · 4h',disabled:config.strategies[0]==='S05'||(config.strategies[0]==='S09'&&config.btcTimeframe==='1h')||(config.strategies[0]==='S08'&&config.macdMtf&&config.macdTrendTimeframe==='4h')},{value:'1h',label:'1 小时 · 1h',disabled:config.strategies[0]==='S05'}]}/></Field>
                <Field label="成交细化周期" id="timeframeDetail"><Select id="timeframeDetail" value={config.timeframeDetail} onChange={value=>set('timeframeDetail',value)} options={[{value:'5m',label:'5 分钟 · 5m'},{value:'',label:'按信号周期'}]}/></Field>
              </div><p className="field-note">指标按信号周期计算，细周期用于撮合与止损。多个交易对可用空格分隔。</p>
              <div className="form-divider"><span>策略参数</span></div>
              {config.strategies[0]==='S08'?<><Field label="MACD 参数预设" id="preset"><Select id="preset" value={preset} onChange={choosePreset} options={[{value:'short',label:'短线 (6,12,9)'},{value:'medium',label:'中线 (12,26,9) · 标准设置'},{value:'long',label:'长线 (19,39,9)'},{value:'custom',label:'自定义'}]}/></Field><div className="form-grid three">{[['macdFast','快线 EMA',2,399],['macdSlow','慢线 EMA',3,400],['macdSignal','信号线 EMA',2,100]].map(([key,label,min,max])=><Field key={key} label={label} id={key}><InputNumber id={key} min={min} max={max} precision={0} value={config[key]} onChange={value=>setMacd(key,value)} controls={false}/></Field>)}</div></>:config.strategies[0]==='S01'?<div className="form-grid">{number('fast','短均线窗口',2,399)}{number('slow','长均线窗口',3,400)}</div>:config.strategies[0]==='S02'?<div className="form-grid">{number('entry','入场通道窗口',2,400)}{number('exit','退出通道窗口',1,400)}</div>:config.strategies[0]==='S09'?null:<p className="field-note fixed-parameters">此策略使用源码默认参数。</p>}
              {config.strategies[0]==='S09'&&<div className="enhancements"><div className="form-divider"><span>BTC 入场与退出信号 · 只交易 ETH</span></div><p className="field-note enhancement-note">BTC MACD金叉买ETH，BTC MACD死叉卖ETH。ETH不计算方向信号；10%固定止损仍有效。</p>
                <Field label="BTC 信号周期" id="btcTimeframe"><Select id="btcTimeframe" value={config.btcTimeframe} onChange={value=>setConfig(old=>({...old,btcTimeframe:value,timeframe:({'1h':60,'4h':240,'1d':1440}[old.timeframe]>{'1h':60,'4h':240,'1d':1440}[value])?'1h':old.timeframe}))} options={[{value:'1d',label:'日线 · 1d'},{value:'4h',label:'4 小时 · 4h'},{value:'1h',label:'1 小时 · 1h'}]}/></Field>
                <div className="form-grid three">{number('btcFast','BTC 快线 EMA',2,399)}{number('btcSlow','BTC 慢线 EMA',3,400)}{number('btcSignal','BTC 信号线 EMA',2,100)}</div><p className="field-note">默认BTC MACD (12,26,9)。BTC K线收盘后触发一次，ETH执行周期只负责信号对齐，5分钟周期细化成交。脚本分别下载ETH成交行情和BTC信号行情。</p>
              </div>}
              {config.strategies[0]==='S08'&&<div className="enhancements"><div className="form-divider"><span>策略增强 · 可选</span></div><p className="field-note enhancement-note">默认全部关闭。开启的条件须与金叉同时满足，只过滤入场，死叉和10%止损仍有效。</p>
                <Enhancement label="多时间框架" description="长周期判断趋势，短周期MACD金叉找入场。" enabled={config.macdMtf} onChange={toggleMtf}>
                  <div className="form-grid"><Field label="长周期趋势" id="macdTrendTimeframe"><Select id="macdTrendTimeframe" value={config.macdTrendTimeframe} onChange={value=>setConfig(old=>({...old,macdTrendTimeframe:value,timeframe:value==='4h'?'1h':old.timeframe}))} options={[{value:'1d',label:'日线 · 1d'},{value:'4h',label:'4 小时 · 4h'}]}/></Field>
                  <Field label="趋势允许做多的条件" id="macdTrendMode"><Select id="macdTrendMode" value={config.macdTrendMode} onChange={value=>set('macdTrendMode',value)} options={[{value:'dif_dea',label:'DIF > DEA'},{value:'zero',label:'DIF > 0'},{value:'both',label:'DIF > DEA 且 DIF > 0'}]}/></Field></div>
                  <div className="form-grid three">{number('macdTrendFast','长周期快线',2,399)}{number('macdTrendSlow','长周期慢线',3,400)}{number('macdTrendSignal','长周期信号线',2,100)}</div>
                  <p className="field-note">短周期沿用上方信号周期与MACD参数；长周期只读取已结束K线。关闭开关不自动修改短周期，请按需调整。首次启用请关闭行情复用。</p>
                </Enhancement>
                <Enhancement label="RSI 区间过滤" description="金叉时RSI在指定区间内才允许入场。" enabled={config.macdRsi} onChange={value=>set('macdRsi',value)}>
                  <div className="form-grid three">{number('macdRsiPeriod','RSI 周期',2,100)}{number('macdRsiMin','RSI 下限（含）',0,99)}{number('macdRsiMax','RSI 上限（含）',1,100)}</div><p className="field-note">默认30–70同时排除区间外信号。设下限0可仅限制超买；此选项不会新增RSI退出条件。</p>
                </Enhancement>
                <Enhancement label="均线趋势过滤" description="信号K线收盘价高于所选均线才允许入场。" enabled={config.macdMa} onChange={value=>set('macdMa',value)}>
                  <div className="form-grid"><Field label="均线类型" id="macdMaType"><Select id="macdMaType" value={config.macdMaType} onChange={value=>set('macdMaType',value)} options={[{value:'ema',label:'EMA · 指数均线'},{value:'sma',label:'SMA · 简单均线'}]}/></Field>{number('macdMaPeriod','均线周期',2,400)}</div><p className="field-note">均线与RSI均按入场信号周期计算，窗口单位为K线数。</p>
                </Enhancement>
                <Enhancement label="成交量确认" description="当前成交量达到此前均量的设定倍数才允许入场。" enabled={config.macdVolume} onChange={value=>set('macdVolume',value)}>
                  <div className="form-grid">{number('macdVolumeWindow','历史均量窗口',2,400)}<Field label="最低成交量倍数" id="macdVolumeMultiplier"><InputNumber id="macdVolumeMultiplier" min={0.1} max={10} step={0.05} precision={2} value={config.macdVolumeMultiplier} onChange={value=>set('macdVolumeMultiplier',value)} controls={false}/></Field></div><p className="field-note">比较当前已结束K线成交量与此前N根均量，基准不包含当前K线。</p>
                </Enhancement>
              </div>}
              <Collapse ghost className="advanced-settings" items={[{key:'funds',label:'资金与费用',children:<div className="form-grid">{number('wallet','初始资金 · USDT',1,1e12)}{number('stake','单笔投入 · USDT',1,1e12)}<Field label="单边手续费 · %" id="fee"><InputNumber id="fee" min={0} max={9.9} step={0.01} value={feeText} onChange={setFeeText} controls={false}/></Field></div>} ]}/>
              <div className="form-actions"><Checkbox checked={config.skipDownload} onChange={e=>set('skipDownload',e.target.checked)}>复用已下载行情</Checkbox><span>首次运行或调整区间时建议关闭</span></div>
              {error&&<Alert className="form-error" type="error" showIcon title={error}/>}
              <Button type="primary" htmlType="submit" block size="large" icon={<PlayCircleOutlined/>} loading={submitting} disabled={!ready||!!active}>{active?'回测运行中':'运行回测'}</Button>
            </Form></Card>
            <aside className="run-summary"><div className="summary-icon"><ExperimentOutlined/></div><h2>本次测试</h2><p>{strategy?.name}</p><dl><div><dt>市场</dt><dd>{config.exchange.toUpperCase()} · 现货</dd></div><div><dt>信号 / 成交</dt><dd>{config.strategies[0]==='S09'?`BTC ${config.btcTimeframe} → ETH ${config.timeframe}`:config.timeframe} / {config.timeframeDetail||config.timeframe}</dd></div><div><dt>初始资金</dt><dd>{money(config.wallet)} <small>USDT</small></dd></div><div><dt>单笔投入</dt><dd>{money(config.stake)} <small>USDT</small></dd></div><div><dt>单边费用</dt><dd>{percent(Number(feeText)/100)}</dd></div><div><dt>固定止损</dt><dd>{config.strategies[0]==='S03'?'5%':'10%'}</dd></div></dl>{config.strategies[0]==='S08'&&<div className="summary-filters"><strong>已开启增强</strong>{macdFilterDescriptions(config).length?macdFilterDescriptions(config).map(label=><span key={label}>{label}</span>):<span>全部关闭 · 基础MACD</span>}</div>}<div className="summary-note"><ClockCircleOutlined/><span>运行完成后，结果会显示在下方，并自动保存到历史回测。</span></div>{active&&active.id!==runId&&<Button type="link" onClick={()=>{setRunId(active.id);sessionStorage.setItem('quant-current-run',active.id)}}>查看正在运行的测试 <ArrowRightOutlined/></Button>}</aside></div>
            {selected&&<div className="current-result"><Results detail={detail} loading={loading} error={detailError}/></div>}
          </>:historyId?<><div className="detail-toolbar"><Button icon={<ArrowLeftOutlined/>} onClick={()=>navigate('history')}>返回历史列表</Button>{detail&&<Button icon={<ReloadOutlined/>} onClick={()=>reuse(detail.job.config)}>使用此参数</Button>}</div><Results detail={detail} loading={loading} error={detailError}/></>:<Card className="history-card"><div className="history-toolbar"><div><h2>测试记录 <span>{jobs.length}</span></h2><p>点击策略名称或右侧箭头查看结果</p></div><div className="history-filters"><Input aria-label="搜索历史回测" prefix={<SearchOutlined/>} placeholder="搜索策略、交易对或日期" value={query} onChange={e=>setQuery(e.target.value)} allowClear/><Select aria-label="筛选回测状态" value={statusFilter} onChange={setStatusFilter} options={[{value:'all',label:'全部状态'},...Object.entries(statusNames).map(([value,label])=>({value,label}))]}/></div></div>{error&&<Alert type="error" showIcon title={error}/>}<Table rowKey="id" loading={!ready} dataSource={filtered} columns={columns} scroll={{x:820}} pagination={{pageSize:8,hideOnSinglePage:true,showSizeChanger:false}} locale={{emptyText:<Empty description={query||statusFilter!=='all'?'没有匹配的回测记录':'还没有回测记录'}/>}}/></Card>}
          <footer>所有测试区间按 UTC · 仅离线研究与回测</footer>
        </main>
      </div>
    </div>
  </ConfigProvider>;
}
