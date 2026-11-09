import { beforeEach,afterEach,vi } from 'vitest';

beforeEach(()=>{
  const data=new Map<string,string>();
  vi.stubGlobal('localStorage',{
    getItem:(key:string)=>data.get(key)??null,
    setItem:(key:string,value:string)=>data.set(key,String(value)),
    removeItem:(key:string)=>data.delete(key),clear:()=>data.clear(),
    key:(index:number)=>Array.from(data.keys())[index]??null,
    get length(){return data.size;},
  });
  vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue(undefined);
  vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>undefined);
  vi.stubGlobal('IntersectionObserver',class {
    observe(){} unobserve(){} disconnect(){} takeRecords(){return [];}
  });
});
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();});
