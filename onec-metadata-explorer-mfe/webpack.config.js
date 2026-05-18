const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const { ModuleFederationPlugin } = require('webpack').container;

const addDevGraphqlHeaders = (proxyReq) => {
  if (!proxyReq.getHeader('X-DataHub-Actor')) {
    proxyReq.setHeader('X-DataHub-Actor', 'urn:li:corpuser:datahub');
  }
};

module.exports = (env, argv) => {
  const isProduction = argv.mode === 'production';
  const publicPath = isProduction
    ? (process.env.MFE_PUBLIC_PATH || 'auto')
    : (process.env.MFE_PUBLIC_PATH || 'http://localhost:3002/');

  return {
    entry: './src/index.tsx',
    mode: isProduction ? 'production' : 'development',
    devtool: isProduction ? 'source-map' : 'eval-cheap-module-source-map',

    devServer: {
      port: 3002,
      hot: true,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, PATCH, OPTIONS',
        'Access-Control-Allow-Headers': 'X-Requested-With, content-type, Authorization',
      },
      historyApiFallback: true,
      watchFiles: ['src/**/*', 'public/**/*'],
      proxy: [
        {
          context: ['/api/graphql'],
          target: process.env.DATAHUB_GRAPHQL_TARGET || 'http://localhost:8080',
          changeOrigin: true,
          secure: false,
          onProxyReq: addDevGraphqlHeaders,
        },
        {
          context: ['/api/v2/graphql'],
          target: process.env.DATAHUB_GRAPHQL_TARGET || 'http://localhost:8080',
          changeOrigin: true,
          secure: false,
          pathRewrite: { '^/api/v2/graphql': '/api/graphql' },
          onProxyReq: addDevGraphqlHeaders,
        },
      ],
    },

    watchOptions: {
      ignored: /node_modules|dist|\.npm-cache/,
    },

    output: {
      publicPath,
      path: path.resolve(__dirname, 'dist'),
      filename: isProduction ? '[name].[contenthash].js' : '[name].js',
      clean: true,
    },

    resolve: {
      extensions: ['.tsx', '.ts', '.js', '.jsx'],
    },

    module: {
      rules: [
        {
          test: /\.(ts|tsx)$/,
          exclude: /node_modules/,
          use: {
            loader: 'ts-loader',
            options: {
              transpileOnly: false,
            },
          },
        },
        {
          test: /\.css$/,
          use: ['style-loader', 'css-loader'],
        },
      ],
    },

    plugins: [
      new ModuleFederationPlugin({
        name: 'onecMetadataExplorerMFE',
        filename: 'remoteEntry.js',
        exposes: {
          './mount': './src/mount.tsx',
        },
        shared: {
          react: {
            singleton: true,
            requiredVersion: '^18.0.0',
          },
          'react-dom': {
            singleton: true,
            requiredVersion: '^18.0.0',
          },
        },
      }),
      new HtmlWebpackPlugin({
        template: './public/index.html',
      }),
    ],

    optimization: {
      splitChunks: false,
    },
  };
};
