
var synthetics = require('Synthetics');
const log = require('SyntheticsLogger');
const https = require('https');

const apiCanaryBlueprint = async function (hostname, path, postData) {
    const verifyRequest = async function (requestOption) {
      return new Promise((resolve, reject) => {
        log.info("Making request with options: " + JSON.stringify(requestOption));
        const req = https.request(requestOption);
        req.on('response', (res) => {
          log.info('Status Code:',res.statusCode);
          log.info('Response Headers:',JSON.stringify(res.headers));
          if (res.statusCode !== 200) {
             reject("Failed: " + requestOption.path);
          }
          res.on('data', (d) => {
            log.info("Response: " + d);
          });
          res.on('end', resolve);
        });
        req.on('error', reject);
        req.write(postData);
        req.end();
      });
    }

    const headers = {"Content-Type":"text/csv"}
    headers['User-Agent'] = [synthetics.getCanaryUserAgentString(), headers['User-Agent']].join(' ');
    const requestOptions = {"hostname":hostname,"method":"POST","path":path,"port":443}
    requestOptions['headers'] = headers;
    await verifyRequest(requestOptions);
};

exports.handler = async () => {
    return await apiCanaryBlueprint("${hostname}", "${path}", "${data}");
};
