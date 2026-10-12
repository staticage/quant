'use client';
import { useEffect, useState } from 'react';
import { Form, InputNumber, Select } from 'antd';

import { MACD_PRESETS, MA_PRESETS, detectPreset } from '../lib/parameter-presets.mjs';
export function ParameterField({label,id,children,wide=false}) {
  return <Form.Item label={label} htmlFor={id} className={wide?'wide':''}>{children}</Form.Item>;
}
function PresetSelector({id,label,presets,values,onChange}) {
  const signature=values.join(',');
  const [selected,setSelected]=useState(()=>detectPreset(presets,values));
  useEffect(()=>{setSelected(detectPreset(presets,values))},[signature,presets]);
  return <ParameterField label={label} id={id}><Select id={id} value={selected}
    onChange={key=>{setSelected(key);const preset=presets.find(p=>p.value===key);if(preset)onChange([...preset.values])}}
    options={[...presets.map(({value,label})=>({value,label})),{value:'custom',label:'自定义'}]}/></ParameterField>;
}
export function MacdParameters({idPrefix,values,onChange,label='MACD 参数预设'}) {
  return <><PresetSelector id={`${idPrefix}-preset`} label={label} presets={MACD_PRESETS} values={[values.fast,values.slow,values.signal]}
    onChange={([fast,slow,signal])=>onChange({fast,slow,signal})}/><div className="form-grid three">
    {[['fast','快线 EMA',2,399],['slow','慢线 EMA',3,400],['signal','信号线 EMA',2,100]].map(([key,label,min,max])=>
      <ParameterField key={key} label={label} id={`${idPrefix}-${key}`}><InputNumber id={`${idPrefix}-${key}`} min={min} max={max}
        precision={0} value={values[key]} onChange={value=>onChange({...values,[key]:value})} controls={false}/></ParameterField>)}
  </div></>;
}
export function MovingAverageParameters({idPrefix,values,onChange,label='双均线参数预设'}) {
  return <><PresetSelector id={`${idPrefix}-preset`} label={label} presets={MA_PRESETS} values={[values.fast,values.slow]}
    onChange={([fast,slow])=>onChange({fast,slow})}/><div className="form-grid">
    {[['fast','短均线窗口',2,399],['slow','长均线窗口',3,400]].map(([key,label,min,max])=>
      <ParameterField key={key} label={label} id={`${idPrefix}-${key}`}><InputNumber id={`${idPrefix}-${key}`} min={min} max={max}
        precision={0} value={values[key]} onChange={value=>onChange({...values,[key]:value})} controls={false}/></ParameterField>)}
  </div><p className="field-note">SMA简单均线，窗口单位为K线数。快捷组合为研究参数，尚不代表收益比较。</p></>;
}
export function ChannelParameters({idPrefix,values,onChange}) {
  return <div className="form-grid">{[['entry','入场通道窗口',2],['exit','退出通道窗口',1]].map(([key,label,min])=>
    <ParameterField key={key} label={label} id={`${idPrefix}-${key}`}><InputNumber id={`${idPrefix}-${key}`} min={min} max={400}
      precision={0} value={values[key]} onChange={value=>onChange({...values,[key]:value})} controls={false}/></ParameterField>)}</div>;
}
