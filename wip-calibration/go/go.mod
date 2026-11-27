module github.com/gothinkster/golang-gin-realworld-example-app

go 1.21

require (
	github.com/gin-gonic/gin v1.10.0
	github.com/go-playground/validator/v10 v10.24.0
	github.com/golang-jwt/jwt/v5 v5.2.1
	github.com/gosimple/slug v1.15.0
	github.com/stretchr/testify v1.10.0
	golang.org/x/crypto v0.32.0
	gorm.io/driver/sqlite v1.5.7
	gorm.io/gorm v1.25.12
)

require (
	github.com/bytedance/sonic v1.11.6 // indirect
	github.com/bytedance/sonic/loader v0.1.1 // indirect
	github.com/cloudwego/base64x v0.1.4 // indirect
	github.com/cloudwego/iasm v0.2.0 // indirect
	github.com/davecgh/go-spew v1.1.1 // indirect
	github.com/gabriel-vasile/mimetype v1.4.8 // indirect
	github.com/gin-contrib/sse v0.1.0 // indirect
	github.com/go-playground/locales v0.14.1 // indirect
	github.com/go-playground/universal-translator v0.18.1 // indirect
	github.com/goccy/go-json v0.10.2 // indirect
	github.com/gosimple/unidecode v1.0.1 // indirect
	github.com/jinzhu/inflection v1.0.0 // indirect
	github.com/jinzhu/now v1.1.5 // indirect
	github.com/json-iterator/go v1.1.12 // indirect
	github.com/klauspost/cpuid/v2 v2.2.7 // indirect
	github.com/leodido/go-urn v1.4.0 // indirect
	github.com/mattn/go-isatty v0.0.20 // indirect
	github.com/mattn/go-sqlite3 v1.14.22 // indirect
	github.com/modern-go/concurrent v0.0.0-20180306012644-bacd9c7ef1dd // indirect
	github.com/modern-go/reflect2 v1.0.2 // indirect
	github.com/pelletier/go-toml/v2 v2.2.2 // indirect
	github.com/pmezard/go-difflib v1.0.0 // indirect
	github.com/twitchyliquid64/golang-asm v0.15.1 // indirect
	github.com/ugorji/go/codec v1.2.12 // indirect
	golang.org/x/arch v0.8.0 // indirect
	golang.org/x/net v0.34.0 // indirect
	golang.org/x/sys v0.29.0 // indirect
	golang.org/x/text v0.21.0 // indirect
	google.golang.org/protobuf v1.34.1 // indirect
	gopkg.in/yaml.v3 v3.0.1 // indirect
)

// Added outside the repo for the calibration sandbox, where Go's module proxy is blocked:
// each module that isn't on GitHub is fetched from its GitHub mirror at the same commit.
replace (
	golang.org/x/arch v0.0.0-20210923205945-b76863e36670 => github.com/golang/arch v0.0.0-20210923205945-b76863e36670
	golang.org/x/arch v0.8.0 => github.com/golang/arch v0.8.0
	golang.org/x/crypto v0.32.0 => github.com/golang/crypto v0.32.0
	golang.org/x/net v0.34.0 => github.com/golang/net v0.34.0
	golang.org/x/sys v0.29.0 => github.com/golang/sys v0.29.0
	golang.org/x/sys v0.5.0 => github.com/golang/sys v0.5.0
	golang.org/x/sys v0.6.0 => github.com/golang/sys v0.6.0
	golang.org/x/text v0.21.0 => github.com/golang/text v0.21.0
	golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 => github.com/golang/xerrors v0.0.0-20191204190536-9bdfabe68543
	google.golang.org/protobuf v1.34.1 => github.com/protocolbuffers/protobuf-go v1.34.1
	gopkg.in/check.v1 v0.0.0-20161208181325-20d25e280405 => github.com/go-check/check v0.0.0-20161208181325-20d25e280405
	gopkg.in/yaml.v3 v3.0.0-20200313102051-9f266ea9e77c => github.com/go-yaml/yaml v0.0.0-20200313102051-9f266ea9e77c
	gopkg.in/yaml.v3 v3.0.1 => github.com/go-yaml/yaml v0.0.0-20220527083530-f6f7691b1fde
	gorm.io/driver/sqlite v1.5.7 => github.com/go-gorm/sqlite v1.5.7
	gorm.io/gorm v1.25.12 => github.com/go-gorm/gorm v1.25.12
	nullprogram.com/x/optparse v1.0.0 => github.com/skeeto/optparse-go v1.0.0
	rsc.io/pdf v0.1.1 => github.com/rsc/pdf v0.1.1
)
