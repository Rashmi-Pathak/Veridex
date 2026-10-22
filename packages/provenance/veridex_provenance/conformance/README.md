# C2PA conformance test trust list

These are the C2PA project's PUBLIC test trust fixtures, vendored from
`contentauth/c2pa-rs` (`sdk/tests/fixtures/certs/trust/`):

- `anchors.pem` - the test root CA bundle (`test_cert_root_bundle.pem`). The certificate subjects
  are marked `FOR TESTING_ONLY`.
- `store.cfg` - the trust config: the extended-key-usage OIDs an allowed C2PA signing certificate
  may carry (id-kp-emailProtection, id-kp-documentSigning, the C2PA claim-signing EKU, etc.).

They are not secrets. They exist so that a manifest signed with the matching C2PA test certificate
(the signing key stays in the gitignored `research/c2pa-test-certs/`) validates as the green
"Trusted" state against this test trust list, demonstrating the trusted path honestly.

A production deployment validates against the C2PA production trust list
(`https://contentcredentials.org/trust/anchors.pem`), not these test anchors. Reaching "Trusted"
here means "trusted against the C2PA conformance test trust list", never a production trust claim.
The UI labels it as such.

`web/public/c2pa-trust/` holds an identical copy that the front end serves so @contentauth/c2pa-web
can validate the same way in the browser.
