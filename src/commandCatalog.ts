import { Clock3, LayoutGrid, StickyNote, FolderOpen, Globe, Volume2, Music, Monitor, Search, Settings2, CircleHelp, type LucideIcon } from 'lucide-react';
import catalog from '../shared/commands.json';
const icons:Record<string,LucideIcon>={'Информация':Clock3,'Приложения':LayoutGrid,'Заметки':StickyNote,'Папки':FolderOpen,'Интернет':Globe,'Звук':Volume2,'Музыка':Music,'Экран':Monitor,'Файлы':Search,'Настройки Windows':Settings2,'Помощь':CircleHelp};
export const commands=catalog.map(c=>({...c,icon:icons[c.category]||CircleHelp}));
