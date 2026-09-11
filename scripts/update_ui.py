from pathlib import Path
p=Path('src/main.tsx')
s=p.read_text(encoding='utf-8-sig')
s=s.replace("import './styles.css';", "import './styles.css';\nimport { MicrophoneSettings } from './MicrophoneSettings';\nimport { commands } from './commandCatalog';")
start=s.index('const commands = [')
end=s.index('\n];',start)+3
s=s[:start]+s[end:]
start=s.index('<section className="settings-card"><div className="settings-card-heading"><Mic size={20}/>')
end=s.index('</section>',start)+len('</section>')
s=s[:start]+s[end:]
s=s.replace('<div className="settings-layout"><section', '<div className="settings-layout"><MicrophoneSettings device={prefs.device} onChange={value=>updatePref(\'device\',value)} autoStop={prefs.autoStop} onAutoStop={()=>updatePref(\'autoStop\',!prefs.autoStop)} disabled={pending||phase===\'listening\'}/><section',1)
s=s.replace("{tab==='commands'&&<><div className=\"command-grid\">{commands.map", "{tab==='commands'&&<><div className=\"search-field\"><Search size={17}/><input aria-label=\"Поиск команд\" placeholder=\"Найти команду: звук, папки, браузер…\" value={search} onChange={e=>setSearch(e.target.value)}/></div><div className=\"command-grid\">{commands.filter(c=>(c.title+' '+c.prompt+' '+c.category).toLowerCase().includes(search.toLowerCase())).map")
s=s.replace('Также можно сказать «Запиши заметку: …». Остальные вопросы Пятница обрабатывает как обычный диалог.', 'Также: «Открой Telegram», «Создай папку на рабочем столе Проекты», «Найди файл отчёт», «Найди в интернете прогноз погоды». Можно добавлять «Пятница», «пожалуйста», «можешь открыть».')
p.write_text(s,encoding='utf-8')
