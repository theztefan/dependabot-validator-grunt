const lodash = require("lodash");
module.exports = value => lodash.get(value, "build");
