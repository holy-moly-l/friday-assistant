import type { CSSProperties } from 'react';
import { Check, Palette } from 'lucide-react';
import type { MotionMode } from './Orb';

export const themes = {
  neon: { name: 'Неон', description: 'Синий и голубой · мягкое свечение', rgb: '86, 207, 255', hue: 210, surface: '#0c121c' },
  lavender: { name: 'Лаванда', description: 'Приглушённый фиолетовый', rgb: '180, 161, 255', hue: 252, surface: '#12101b' },
  graphite: { name: 'Графит', description: 'Нейтральный и спокойный', rgb: '172, 185, 205', hue: 215, surface: '#111419' },
  mint: { name: 'Мята', description: 'Мягкий бирюзовый', rgb: '117, 205, 180', hue: 165, surface: '#0d1615' },
} as const;
export type ThemeId = keyof typeof themes;
export function themeId(value: unknown): ThemeId {
  return typeof value === 'string' && Object.hasOwn(themes, value) ? value as ThemeId : 'neon';
}

export function AppearanceSettings({ value, onChange, motion, onMotion }: { value: ThemeId; onChange: (value: ThemeId) => void; motion:MotionMode; onMotion:(mode:MotionMode)=>void }) {
  return <section className="settings-card appearance-card">
    <div className="settings-card-heading"><Palette size={22}/><h2>Цветовая тема</h2></div>
    <div className="theme-options" role="group" aria-label="Стиль интерфейса">
      {(Object.entries(themes) as [ThemeId, typeof themes[ThemeId]][]).map(([id, theme]) => <button key={id} type="button" className={'theme-option '+(value===id?'selected':'')} aria-pressed={value===id} aria-label={'Стиль '+theme.name} onClick={()=>onChange(id)} style={{'--swatch-rgb':theme.rgb,'--swatch-surface':theme.surface} as CSSProperties}>
        <span className="theme-preview" aria-hidden="true"><span className="preview-sidebar"><i/><i/><i/></span><span className="preview-main"><span className="preview-orb"/><span className="preview-input"><i/></span></span></span>
        <span className="theme-option-title">{theme.name}<span className="theme-check">{value===id&&<Check size={13}/>}</span></span>
        <span className="theme-option-description">{theme.description}</span>
      </button>)}
    </div>
    <div className="settings-row motion-setting"><div><strong>Анимация ядра</strong><p>{motion==='interactive'?'Вращайте мышью; пробел на ядре ставит движение на паузу.':motion==='ambient'?'Медленное вращение без реакции на курсор.':'Неподвижное ядро.'}</p></div><select aria-label="Анимация ядра" value={motion} onChange={e=>onMotion(e.target.value as MotionMode)}><option value="interactive">Реакция на курсор</option><option value="ambient">Спокойное вращение</option><option value="still">Без движения</option></select></div>
  </section>;
}
