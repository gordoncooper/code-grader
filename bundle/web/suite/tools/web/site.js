(function(){
  var toast=document.createElement('div');toast.className='toast';toast.setAttribute('role','status');(document.querySelector('main')||document.body).appendChild(toast);
  function say(msg){toast.textContent=msg;toast.classList.add('show');clearTimeout(say.t);say.t=setTimeout(function(){toast.classList.remove('show')},1600)}
  function copy(text){
    if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(text).then(function(){say('Copied')},fallback)}else{fallback()}
    function fallback(){var t=document.createElement('textarea');t.value=text;t.style.position='fixed';t.style.opacity='0';document.body.appendChild(t);t.select();try{document.execCommand('copy');say('Copied')}catch(e){say('Press Ctrl/Cmd+C to copy')}document.body.removeChild(t)}
  }
  // Absolute base URL of the site (directory containing index.html), derived from this script's URL.
  var script=document.currentScript&&document.currentScript.src;
  var base=script?new URL('../',script).href:new URL('./',location.href).href;
  var isFile=location.protocol==='file:';
  var shown=isFile?'https://your-server/path/':base;
  document.querySelectorAll('[data-base]').forEach(function(el){el.textContent=el.textContent.split('{BASE}').join(shown)});
  if(isFile){document.querySelectorAll('.file-note').forEach(function(el){el.hidden=false})}
  document.querySelectorAll('[data-copy]').forEach(function(btn){
    btn.addEventListener('click',function(){
      var sel=btn.getAttribute('data-copy'),text;
      if(sel.charAt(0)==='#'){var el=document.querySelector(sel);text=el?el.textContent:''}
      else{text=new URL(sel,location.href).href}
      copy(text.trim());
    });
  });
  var mb=document.querySelector('.menu-btn');
  if(mb){mb.addEventListener('click',function(){document.body.classList.toggle('nav-open')})}
  // Wide tables and code blocks scroll sideways on small screens: put the ones that do in the Tab
  // order, so keyboard users can scroll them too (and only those, to keep the Tab order short).
  function markScrollers(){
    document.querySelectorAll('table, pre').forEach(function(el){
      var scrolls=el.scrollWidth>el.clientWidth+1;
      if(scrolls&&!el.hasAttribute('tabindex')){el.setAttribute('tabindex','0');el.dataset.scrollFocus='1'}
      else if(!scrolls&&el.dataset.scrollFocus){el.removeAttribute('tabindex');delete el.dataset.scrollFocus}
    });
  }
  var mt;function later(){clearTimeout(mt);mt=setTimeout(markScrollers,60)}
  window.addEventListener('load',markScrollers);window.addEventListener('resize',later);
  if(window.MutationObserver){new MutationObserver(later).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden','open','class']})}
})();
