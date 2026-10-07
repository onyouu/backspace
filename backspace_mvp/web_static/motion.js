/* Optional enhancement: every action remains usable when any GSAP plugin fails. */
const Motion = (() => {
  let context=null, media=null, split=null;
  const preference=matchMedia('(prefers-reduced-motion: reduce)');
  const enabled=()=>!!window.gsap&&!preference.matches&&localStorage.getItem('backspace-motion')!=='off';
  function clear(){if(window.gsap)gsap.killTweensOf('#main *');split?.revert();split=null;media?.revert();media=null;context?.revert();context=null;}
  function enter(page){
    clear(); if(!enabled())return;
    const plugins=['Flip','ScrollTrigger','SplitText','DrawSVGPlugin'].map(n=>window[n]).filter(Boolean);
    gsap.registerPlugin(...plugins);
    media=gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)',()=>{
      context=gsap.context(()=>{
        const first=page==='overview'&&!sessionStorage.getItem('backspace-intro');
        if(first){
          sessionStorage.setItem('backspace-intro','1');
          const title=document.querySelector('.hero-title');
          if(window.SplitText&&title)split=SplitText.create(title,{type:'lines',mask:'lines',autoSplit:true,onSplit(self){return gsap.from(self.lines,{yPercent:105,opacity:0,duration:.65,stagger:.1,ease:'power3.out'});}});
          else if(title)gsap.from(title,{y:16,opacity:0,duration:.55});
          if(document.querySelector('.hero-art .art-card'))gsap.from('.hero-art .art-card',{y:14,opacity:0,stagger:.12,duration:.5,delay:.12});
          if(window.DrawSVGPlugin&&document.querySelector('.hero-connection'))gsap.from('.hero-connection',{drawSVG:0,duration:.75,delay:.25});
        }else gsap.from('.intro, .hero',{y:10,opacity:0,duration:.25,ease:'power2.out'});
        if(window.ScrollTrigger)document.querySelectorAll('[data-reveal]').forEach(el=>gsap.from(el,{y:16,opacity:0,duration:.35,scrollTrigger:{trigger:el,start:'top 94%',once:true}}));
      },document.querySelector('#main'));
      return()=>{split?.revert();split=null;context?.revert();context=null;};
    });
  }
  function select(edges){if(enabled()&&window.DrawSVGPlugin&&edges.length)gsap.fromTo(edges,{drawSVG:'0%'},{drawSVG:'100%',duration:.35,overwrite:true});}
  preference.addEventListener('change',()=>{clear();});
  return {enabled,clear,enter,select};
})();
