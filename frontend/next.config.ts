import type {NextConfig} from 'next';
const config:NextConfig={
  output:'standalone',
  poweredByHeader:false,
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
