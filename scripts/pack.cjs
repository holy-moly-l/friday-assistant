const {packager}=require('@electron/packager');
const path=require('node:path');
(async()=>{
  await packager({dir:'.',name:'Friday',platform:'win32',arch:'x64',out:'release',overwrite:true,icon:'public/friday.ico',
    executableName:'Friday',appCopyright:'Friday · Personal Intelligence',appVersion:require('../package.json').version,
    win32metadata:{CompanyName:'Friday',FileDescription:'Friday — local voice assistant',ProductName:'Friday'},
    ignore:[/^\/(release|\.venv|\.venv-tts|models|data|tests|scripts|src|backend|\.git)(\/|$)/,/^\/tsconfig/,/^\/vite\.config/,/^\/README/],
    prune:true,
  });
  console.log('PACKAGED: release/Friday-win32-x64/Friday.exe');
})().catch(e=>{console.error(e);process.exit(1)});
