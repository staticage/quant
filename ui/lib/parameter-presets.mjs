// 快捷参数为研究配置，不代表已经比较过绩效。
export const MACD_PRESETS=[{value:'short',label:'短线 (6,12,9)',values:[6,12,9]},
  {value:'medium',label:'中线 (12,26,9) · 标准设置',values:[12,26,9]},
  {value:'long',label:'长线 (19,39,9)',values:[19,39,9]}];
export const MA_PRESETS=[{value:'short',label:'短线 (5,20)',values:[5,20]},
  {value:'medium',label:'中线 (20,60)',values:[20,60]},
  {value:'long',label:'长线 (50,200)',values:[50,200]}];
export function detectPreset(presets,values){return presets.find(p=>p.values.every((value,i)=>value===values[i]))?.value||'custom';}
