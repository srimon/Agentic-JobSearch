import type {NextConfig} from 'next';
import {mountPath} from './app/base-path.mjs';
// Job Search answers on https://bagala.ai/jobsearch/ and, unchanged, on https://jobs.bagala.ai/
// and http://localhost:3105/. Next bakes the prefix into the build — the asset URLs under
// /_next, the icon link and the sources of the rewrites and headers below all carry it — so one
// build is made under the prefix, and platform/gateway/nginx.conf gives the prefix to a request
// that arrives at the root shape. app/paths.ts reads the same value, and everything the browser
// is asked to fetch or follow is built from the address it is actually on.
const BASE_PATH=mountPath(process.env.NEXT_PUBLIC_JOBSEARCH_BASE_PATH??'/jobsearch');
const config:NextConfig={
  output:'standalone',
  poweredByHeader:false,
  ...(BASE_PATH?{basePath:BASE_PATH}:{}),
  // Embedded upstream interfaces own their slash-sensitive routes and assets.
  skipTrailingSlashRedirect:true,
  // /__hub/enquiries is normally answered by the gateway in front; this keeps the footer working on direct access too.
  async rewrites(){return [{source:'/api/:path*',destination:'http://api:8100/api/:path*'},{source:'/__hub/enquiries',destination:'http://api:8100/api/enquiries'}]},
  async headers(){return [{source:'/:path*',headers:[
    {key:'X-Content-Type-Options',value:'nosniff'},
    {key:'X-Frame-Options',value:'DENY'},
    {key:'Referrer-Policy',value:'no-referrer'}
  ]},{source:'/api/data-model/report/:path*',headers:[{key:'X-Frame-Options',value:'SAMEORIGIN'}]}]}
};
export default config;
