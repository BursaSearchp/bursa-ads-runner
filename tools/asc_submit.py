"""Submit an iOS version for App Store review, released automatically on approval.
  python asc_submit.py 2.0.3 "What's New text"
Needs ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_P8. Prints states only (the log is public)."""
import os, sys, time
import jwt, requests

BUNDLE = 'fresherforgev2.com'
API = 'https://api.appstoreconnect.apple.com'


def token():
    now = int(time.time())
    return jwt.encode({'iss': os.environ['ASC_ISSUER_ID'], 'iat': now, 'exp': now + 600, 'aud': 'appstoreconnect-v1'},
                      os.environ['ASC_KEY_P8'], algorithm='ES256', headers={'kid': os.environ['ASC_KEY_ID']})


def call(method, path, body=None, ok=(200, 201, 204), **params):
    r = requests.request(method, API + path, json=body, params=params,
                         headers={'Authorization': f'Bearer {token()}', 'Content-Type': 'application/json'})
    if r.status_code not in ok:
        sys.exit(f'{method} {path.split("?")[0]} -> {r.status_code}: {r.text[:600]}')
    return r.json() if r.text else {}


def main():
    version, notes = sys.argv[1], sys.argv[2]
    app = call('GET', '/v1/apps', **{'filter[bundleId]': BUNDLE})['data'][0]['id']

    # the processed build for this version (it can take a while after upload)
    build = None
    for _ in range(60):
        bs = call('GET', '/v1/builds', **{'filter[app]': app, 'filter[preReleaseVersion.version]': version,
                                          'sort': '-uploadedDate', 'limit': 5})['data']
        valid = [b for b in bs if b['attributes'].get('processingState') == 'VALID']
        if valid:
            build = valid[0]
            break
        print('waiting for the build to finish processing...', [b['attributes'].get('processingState') for b in bs])
        time.sleep(30)
    if not build:
        sys.exit('no processed build for ' + version)
    print('build', build['attributes']['version'], 'VALID')

    # the version: reuse 2.0.3 if it exists, else an editable one, else create
    vs = call('GET', f'/v1/apps/{app}/appStoreVersions', **{'filter[platform]': 'IOS', 'limit': 10})['data']
    for v in vs:
        print('existing version', v['attributes']['versionString'], v['attributes']['appStoreState'])
    editable = ('PREPARE_FOR_SUBMISSION', 'DEVELOPER_REJECTED', 'REJECTED', 'METADATA_REJECTED')
    v = next((x for x in vs if x['attributes']['versionString'] == version), None) or \
        next((x for x in vs if x['attributes']['appStoreState'] in editable), None)
    attrs = {'versionString': version, 'releaseType': 'AFTER_APPROVAL'}
    if v:
        vid = v['id']
        call('PATCH', f'/v1/appStoreVersions/{vid}', {'data': {'type': 'appStoreVersions', 'id': vid, 'attributes': attrs}})
    else:
        vid = call('POST', '/v1/appStoreVersions', {'data': {'type': 'appStoreVersions',
            'attributes': {'platform': 'IOS', **attrs},
            'relationships': {'app': {'data': {'type': 'apps', 'id': app}}}}})['data']['id']
    print('version', version, 'set to release automatically after approval')

    call('PATCH', f'/v1/appStoreVersions/{vid}/relationships/build', {'data': {'type': 'builds', 'id': build['id']}})
    print('build attached')

    for loc in call('GET', f'/v1/appStoreVersions/{vid}/appStoreVersionLocalizations')['data']:
        call('PATCH', f'/v1/appStoreVersionLocalizations/{loc["id"]}',
             {'data': {'type': 'appStoreVersionLocalizations', 'id': loc['id'], 'attributes': {'whatsNew': notes}}})
        print("What's New set for", loc['attributes']['locale'])

    # a review submission: reuse an open one, else create; add the version; submit
    subs = call('GET', '/v1/reviewSubmissions', **{'filter[app]': app, 'filter[platform]': 'IOS',
                                                   'filter[state]': 'READY_FOR_REVIEW'})['data']
    sid = subs[0]['id'] if subs else call('POST', '/v1/reviewSubmissions', {'data': {'type': 'reviewSubmissions',
        'attributes': {'platform': 'IOS'}, 'relationships': {'app': {'data': {'type': 'apps', 'id': app}}}}})['data']['id']
    call('POST', '/v1/reviewSubmissionItems', {'data': {'type': 'reviewSubmissionItems', 'relationships': {
        'reviewSubmission': {'data': {'type': 'reviewSubmissions', 'id': sid}},
        'appStoreVersion': {'data': {'type': 'appStoreVersions', 'id': vid}}}}}, ok=(201, 409))
    r = call('PATCH', f'/v1/reviewSubmissions/{sid}', {'data': {'type': 'reviewSubmissions', 'id': sid,
                                                              'attributes': {'submitted': True}}})
    print('submitted for review:', r['data']['attributes'].get('state'))


if __name__ == '__main__':
    main()
