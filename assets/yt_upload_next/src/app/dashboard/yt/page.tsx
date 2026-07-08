"use client";
import {
  AlertCircle,
  BarChart3,
  Edit2,
  Eye,
  Loader2,
  Plus,
  Sparkles,
  Upload,
  Users,
  X,
  Youtube,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";
import UIWrapper from "@/components/myComponents/UIWrapper";

const DashboardPage = () => {
  const router = useRouter();
  const [accessToken, setAccessToken] = useState("");
  const [channelData, setChannelData] = useState<any>(null);
  const [analytics, setAnalytics] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ message: string; code?: number } | null>(
    null,
  );

  // Upload State
  const [uploading, setUploading] = useState(false);
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [privacy, setPrivacy] = useState("private");

  // Edit Dialog State
  const [editingVideo, setEditingVideo] = useState<any>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editTags, setEditTags] = useState("");
  const [targetAudience, setTargetAudience] = useState("General Audience");
  const [generatingHints, setGeneratingHints] = useState(false);
  const [saving, setSaving] = useState(false);
  const [aiHints, setAiHints] = useState<{
    titles: string[];
    descriptions: string[];
    tags: string[];
    general?: string;
  } | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("youtube_access_token");
    if (!token) {
      router.push("/sign-in");
      return;
    }
    setAccessToken(token);
  }, [router]);

  const fetchChannelData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/google", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "getChannelData", accessToken }),
      });
      const result = await response.json();

      if (result.success) {
        setChannelData(result);
      } else {
        // Handle API errors
        const errorMessage = result.error || "Failed to fetch channel data";
        const errorCode = result.code || response.status;
        setError({ message: errorMessage, code: errorCode });

        if (errorCode === 401) {
          toast.error(
            "Authentication failed. Please reconnect your YouTube account.",
          );
        } else {
          toast.error(errorMessage);
        }
      }
    } catch (error: any) {
      console.error("Channel data fetch error:", error);
      const errorMessage = error.message || "Failed to fetch channel data";
      setError({ message: errorMessage });
      toast.error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  const fetchAnalytics = useCallback(async () => {
    try {
      const response = await fetch("/api/google", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "getAnalytics", accessToken }),
      });
      const result = await response.json();

      if (result.success) {
        setAnalytics(result);
      } else {
        const errorCode = result.code || response.status;
        if (errorCode === 401) {
          console.error("Analytics auth error:", result.error);
        } else {
          console.error("Analytics fetch error:", result.error);
        }
      }
    } catch (error: any) {
      console.error("Analytics fetch error:", error);
    }
  }, [accessToken]);

  const handleUpload = async () => {
    if (!videoFile || !title) {
      toast.error("Please select a video and enter a title");
      return;
    }

    setUploading(true);
    const formData = new FormData();
    formData.append("action", "uploadVideo");
    formData.append("accessToken", accessToken);
    formData.append("videoFile", videoFile);
    formData.append("title", title);
    formData.append("description", description);
    formData.append("tags", tags);
    formData.append("privacy", privacy);

    try {
      const response = await fetch("/api/google", {
        method: "POST",
        body: formData,
      });
      const result = await response.json();

      if (result.success) {
        toast.success("Video uploaded successfully!");
        setVideoFile(null);
        setTitle("");
        setDescription("");
        setTags("");
        fetchChannelData(); // Refresh list
      } else {
        throw new Error(result.error || "Upload failed");
      }
    } catch (error) {
      toast.error("Failed to upload video");
      console.error(error);
    } finally {
      setUploading(false);
    }
  };

  const handleEditVideo = async (video: any) => {
    const _videoId = video.snippet?.resourceId?.videoId || video.id;
    setEditingVideo(video);
    setEditTitle(video.snippet?.title || "");
    setEditDescription(video.snippet?.description || "");
    setEditTags(video.snippet?.tags?.join(", ") || "");
    setTargetAudience("General Audience");
    setAiHints(null);
  };

  const handleGenerateHints = async () => {
    if (!editTitle || !editDescription) {
      toast.error("Please provide both title and description");
      return;
    }

    setGeneratingHints(true);
    const toastId = toast.loading("Generating AI suggestions...");

    try {
      const response = await fetch("/api/gemini", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_topic: editTitle,
          video_description: editDescription,
          target_audience: targetAudience,
          keywords: editTags
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean),
        }),
      });

      const result = await response.json();

      if (result.success) {
        const data = result.data;
        // Map backend response to frontend aiHints structure
        setAiHints({
          titles: data.titles || [],
          descriptions: data.description ? [data.description] : [],
          tags: data.tags ? [data.tags.join(", ")] : [],
          general: data.hashtags
            ? `Suggested hashtags: ${data.hashtags.join(" ")}`
            : undefined,
        });
        toast.success("AI suggestions generated!", { id: toastId });
      } else {
        throw new Error(result.message || "Failed to generate hints");
      }
    } catch (error: any) {
      console.error("AI Hints Error:", error);
      toast.error(error.message || "Failed to generate suggestions", {
        id: toastId,
      });
    } finally {
      setGeneratingHints(false);
    }
  };

  const handleSaveMetadata = async () => {
    if (!editingVideo || !editTitle) {
      toast.error("Title is required");
      return;
    }

    const videoId =
      editingVideo.snippet?.resourceId?.videoId || editingVideo.id;
    setSaving(true);
    const toastId = toast.loading("Updating video metadata...");

    try {
      const response = await fetch("/api/google", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "updateVideo",
          accessToken,
          videoId,
          title: editTitle,
          description: editDescription,
          tags: editTags
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean),
        }),
      });

      const result = await response.json();

      if (result.success) {
        toast.success("Video updated successfully!", { id: toastId });
        setEditingVideo(null);
        setAiHints(null); // Clear AI hints
        fetchChannelData(); // Refresh list
      } else {
        throw new Error(result.error || "Update failed");
      }
    } catch (error: any) {
      console.error("Update Error:", error);
      toast.error(error.message || "Failed to update video", { id: toastId });
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    if (accessToken) {
      fetchChannelData();
      fetchAnalytics();
    }
  }, [accessToken, fetchAnalytics, fetchChannelData]);

  if (!accessToken) return null;

  return (
    <UIWrapper classname="min-h-screen bg-gradient-to-br from-gray-950 via-black to-black">
      <div className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-4 pb-8 overflow-y-auto">
        {/* Loading State */}
        {loading && !channelData && (
          <div className="space-y-6">
            {/* Stats Skeleton */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="glass rounded-2xl p-6 border border-white/10 animate-pulse"
                >
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-5 h-5 bg-white/10 rounded"></div>
                    <div className="w-24 h-4 bg-white/10 rounded"></div>
                  </div>
                  <div className="w-20 h-8 bg-white/10 rounded"></div>
                </div>
              ))}
            </div>

            {/* Content Skeleton */}
            <div className="glass rounded-2xl p-6 border border-white/10 animate-pulse">
              <div className="w-32 h-6 bg-white/10 rounded mb-6"></div>
              <div className="space-y-3">
                <div className="w-full h-12 bg-white/10 rounded"></div>
                <div className="w-full h-12 bg-white/10 rounded"></div>
                <div className="w-full h-12 bg-white/10 rounded"></div>
              </div>
            </div>
          </div>
        )}

        {/* Error State */}
        {error && !loading && (
          <div className="glass rounded-2xl p-8 border border-red-500/20 bg-red-500/5">
            <div className="flex flex-col items-center text-center space-y-4">
              <div className="p-4 rounded-full bg-red-500/10">
                <AlertCircle className="w-12 h-12 text-red-400" />
              </div>
              <div>
                <h3 className="text-xl font-bold text-white mb-2">
                  {error.code === 401
                    ? "Authentication Required"
                    : "Error Loading Data"}
                </h3>
                <p className="text-gray-400 max-w-md">
                  {error.code === 401
                    ? "Your YouTube authentication has expired or is invalid. Please reconnect your account to continue."
                    : error.message}
                </p>
              </div>
              {error.code === 401 ? (
                <button
                  type="button"
                  onClick={() => {
                    localStorage.removeItem("youtube_access_token");
                    router.push("/sign-in");
                  }}
                  className="px-6 py-3 bg-gradient-to-r from-red-600 via-pink-600 to-purple-600 hover:from-red-700 hover:via-pink-700 hover:to-purple-700 text-white font-medium rounded-xl transition-all shadow-lg hover:shadow-red-500/50"
                >
                  Reconnect YouTube Account
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    localStorage.clear();
                    cookieStore.delete("youtube_access_token");
                    cookieStore.delete("user_id");
                    cookieStore.delete("next-auth.session-token");
                    router.push("/sign-in");
                  }}
                  className="px-6 py-3 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-700 hover:to-blue-700 text-white font-medium rounded-xl transition-all shadow-lg hover:shadow-cyan-500/50"
                >
                  sign out
                </button>
              )}
            </div>
          </div>
        )}

        {/* Main Content - Only show if not loading and no error */}
        {!loading && !error && (
          <div className="space-y-6">
            {/* Channel Overview */}
            <Suspense fallback={<div>Loading...</div>}>
              {channelData && (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
                  <div className="glass rounded-2xl p-6 border border-red-500/20 bg-gradient-to-br from-red-500/5 to-transparent hover:border-red-500/40 transition-all duration-300">
                    <div className="flex items-center gap-3 mb-4">
                      <div className="p-2 rounded-lg bg-red-500/10">
                        <Users className="w-5 h-5 text-red-400" />
                      </div>
                      <span className="text-white font-medium">
                        Subscribers
                      </span>
                    </div>
                    <div className="text-2xl sm:text-3xl font-bold bg-gradient-to-r from-red-400 to-pink-400 bg-clip-text text-transparent">
                      {channelData.channel?.statistics?.subscriberCount || "0"}
                    </div>
                  </div>

                  <div className="glass rounded-2xl p-6 border border-cyan-500/20 bg-gradient-to-br from-cyan-500/5 to-transparent hover:border-cyan-500/40 transition-all duration-300">
                    <div className="flex items-center gap-3 mb-4">
                      <div className="p-2 rounded-lg bg-cyan-500/10">
                        <Eye className="w-5 h-5 text-cyan-400" />
                      </div>
                      <span className="text-white font-medium">
                        Total Views
                      </span>
                    </div>
                    <div className="text-3xl font-bold bg-gradient-to-r from-cyan-400 to-blue-400 bg-clip-text text-transparent">
                      {channelData.channel?.statistics?.viewCount || "0"}
                    </div>
                  </div>

                  <div className="glass rounded-2xl p-6 border border-purple-500/20 bg-gradient-to-br from-purple-500/5 to-transparent hover:border-purple-500/40 transition-all duration-300">
                    <div className="flex items-center gap-3 mb-4">
                      <div className="p-2 rounded-lg bg-purple-500/10">
                        <BarChart3 className="w-5 h-5 text-purple-400" />
                      </div>
                      <span className="text-white font-medium">Videos</span>
                    </div>
                    <div className="text-3xl font-bold bg-gradient-to-r from-purple-400 to-pink-400 bg-clip-text text-transparent">
                      {channelData.channel?.statistics?.videoCount || "0"}
                    </div>
                  </div>
                </div>
              )}
            </Suspense>
            {/* Upload Section */}
            <div className="glass rounded-2xl p-6 border border-white/10 hover:border-red-500/30 transition-colors duration-300">
              <h3 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                <div className="p-2 rounded-lg bg-gradient-to-br from-red-500/20 to-pink-500/20">
                  <Upload className="w-5 h-5 text-red-400" />
                </div>
                Upload Video
              </h3>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:gap-6">
                <div className="space-y-4">
                  <div className="border-2 border-dashed border-white/10 rounded-xl p-8 text-center hover:border-red-500/50 transition-colors relative">
                    <input
                      type="file"
                      accept="video/*"
                      onChange={(e) =>
                        setVideoFile(e.target.files?.[0] || null)
                      }
                      className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                    />
                    {videoFile ? (
                      <div className="text-green-400 font-medium break-all">
                        {videoFile.name}
                      </div>
                    ) : (
                      <div className="text-gray-400">
                        <Upload className="w-8 h-8 mx-auto mb-2 opacity-50" />
                        <p>Click or drag video file here</p>
                      </div>
                    )}
                  </div>

                  <select
                    value={privacy}
                    onChange={(e) => setPrivacy(e.target.value)}
                    className="w-full bg-black/20 border border-white/10 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-red-500/50"
                  >
                    <option value="private">Private</option>
                    <option value="unlisted">Unlisted</option>
                    <option value="public">Public</option>
                  </select>
                </div>

                <div className="space-y-4">
                  <input
                    type="text"
                    placeholder="Video Title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="w-full bg-black/20 border border-white/10 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-red-500/50"
                  />
                  <textarea
                    placeholder="Description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={4}
                    className="w-full bg-black/20 border border-white/10 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-red-500/50 resize-none"
                  />
                  <input
                    type="text"
                    placeholder="Tags (comma separated)"
                    value={tags}
                    onChange={(e) => setTags(e.target.value)}
                    className="w-full bg-black/20 border border-white/10 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-red-500/50"
                  />
                  <button
                    type="button"
                    onClick={handleUpload}
                    disabled={uploading || !videoFile || !title}
                    className="w-full py-3 bg-gradient-to-r from-red-600 via-pink-600 to-purple-600 text-white font-medium rounded-xl flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed hover:shadow-lg hover:shadow-red-500/25 transition-all duration-300"
                  >
                    {uploading ? (
                      <>
                        <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        Uploading...
                      </>
                    ) : (
                      <>
                        <Upload className="w-5 h-5" />
                        Upload Video
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>

            {/* Analytics */}
            <Suspense fallback={<div>Loading...</div>}>
              {analytics && (
                <div className="glass rounded-2xl p-6 border border-purple-500/20 bg-gradient-to-br from-purple-500/5 to-transparent hover:border-purple-500/30 transition-colors duration-300">
                  <h3 className="text-xl font-bold text-white mb-4">
                    30-Day Analytics
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="text-center">
                      <div className="text-lg font-bold text-white">
                        {analytics.overview?.rows?.[0]?.[0] || "0"}
                      </div>
                      <div className="text-sm text-gray-400">Views</div>
                    </div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-white">
                        {Math.round(
                          (analytics.overview?.rows?.[0]?.[1] || 0) / 60,
                        )}{" "}
                        hrs
                      </div>
                      <div className="text-sm text-gray-400">Watch Time</div>
                    </div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-white">
                        {analytics.overview?.rows?.[0]?.[2] || "0"}
                      </div>
                      <div className="text-sm text-gray-400">Likes</div>
                    </div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-white">
                        +{analytics.overview?.rows?.[0]?.[5] || "0"}
                      </div>
                      <div className="text-sm text-gray-400">Subscribers</div>
                    </div>
                  </div>
                </div>
              )}
            </Suspense>

            <Suspense fallback={<div>Loading...</div>}>
              {/* Recent Videos */}
              {channelData?.recentVideos && (
                <div className="glass rounded-2xl p-6 border border-white/10 hover:border-cyan-500/30 transition-colors duration-300">
                  <h3 className="text-xl font-bold text-white mb-4">
                    All Videos ({channelData.recentVideos.length})
                  </h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 sm:gap-4">
                    {channelData.recentVideos.map((video: any) => (
                      <div
                        key={
                          video.snippet?.resourceId?.videoId ||
                          video.id ||
                          `video-${Math.random()}`
                        }
                        className="glass rounded-xl overflow-hidden hover:scale-105 hover:border-red-500/30 transition-all duration-300 group border border-white/10"
                      >
                        <div className="aspect-video relative bg-black/50">
                          {video.snippet?.thumbnails?.medium?.url ? (
                            <img
                              src={video.snippet.thumbnails.medium.url}
                              alt={video.snippet.title}
                              className="w-full h-full object-cover"
                            />
                          ) : (
                            <div className="w-full h-full flex items-center justify-center">
                              <Youtube className="w-12 h-12 text-white/20" />
                            </div>
                          )}
                          <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/60 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                            <a
                              href={`https://www.youtube.com/watch?v=${video.snippet?.resourceId?.videoId || video.id}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="p-3 bg-gradient-to-r from-red-600 to-pink-600 rounded-full text-white transform scale-0 group-hover:scale-100 transition-transform shadow-lg hover:shadow-red-500/50"
                            >
                              <Eye className="w-5 h-5" />
                            </a>
                          </div>
                        </div>
                        <div className="p-4">
                          <h4
                            className="text-white font-medium line-clamp-2 mb-2 text-sm sm:text-base"
                            title={video.snippet?.title}
                          >
                            {video.snippet?.title}
                          </h4>
                          <div className="flex items-center justify-between text-xs text-gray-400 mb-2">
                            <div className="flex items-center gap-1">
                              <Eye className="w-3 h-3" />
                              <span>
                                {video.statistics?.viewCount
                                  ? parseInt(
                                      video.statistics.viewCount,
                                      10,
                                    ).toLocaleString()
                                  : "0"}{" "}
                                views
                              </span>
                            </div>
                            <span>
                              {new Date(
                                video.snippet?.publishedAt,
                              ).toLocaleDateString()}
                            </span>
                          </div>
                          <div className="flex items-center justify-between text-xs">
                            <span
                              className={`px-2 py-1 rounded-full font-medium ${
                                video.status?.privacyStatus === "public"
                                  ? "bg-green-500/20 text-green-300 border border-green-500/30"
                                  : video.status?.privacyStatus === "private"
                                    ? "bg-red-500/20 text-red-300 border border-red-500/30"
                                    : "bg-yellow-500/20 text-yellow-300 border border-yellow-500/30"
                              }`}
                            >
                              {video.status?.privacyStatus}
                            </span>
                            <button
                              type="button"
                              onClick={() => handleEditVideo(video)}
                              className="p-2 sm:p-1.5 rounded-lg bg-gradient-to-br from-purple-500/20 to-pink-500/20 hover:from-purple-500/30 hover:to-pink-500/30 text-purple-300 hover:text-purple-200 transition-all duration-200 border border-purple-500/20 min-h-[2.5rem] sm:min-h-[auto]"
                              title="Edit metadata"
                            >
                              <Edit2 className="w-3 h-3" />
                            </button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Suspense>
          </div>
        )}
      </div>

      {/* Edit Metadata Dialog */}
      {editingVideo && (
        <div className="fixed inset-0 bg-black/90 backdrop-blur-sm z-50 flex items-center justify-center p-2 sm:p-4">
          <div className="rounded-2xl max-w-4xl w-full max-h-[95vh] sm:max-h-[90vh] overflow-y-auto border border-white/20 mx-2 sm:mx-0">
            <div className="sticky top-0 glass border-b border-white/10 p-6 flex items-center justify-between backdrop-blur-xl">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-gradient-to-br from-red-500/20 to-purple-500/20">
                  <Edit2 className="w-5 h-5 text-red-400" />
                </div>
                <div>
                  <h2 className="text-xl font-bold text-white">
                    Edit Video Metadata
                  </h2>
                  <p className="text-sm text-gray-400">
                    Update your video details with AI assistance
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setEditingVideo(null)}
                className="p-2 rounded-lg hover:bg-white/10 transition-colors"
              >
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>

            <div className="p-6 space-y-6">
              {/* Current Thumbnail */}
              <div className="aspect-video rounded-xl overflow-hidden bg-black/50 max-w-sm">
                {editingVideo.snippet?.thumbnails?.medium?.url && (
                  <img
                    src={editingVideo.snippet.thumbnails.medium.url}
                    alt={editingVideo.snippet.title}
                    className="w-full h-full object-cover"
                  />
                )}
              </div>

              {/* Title */}
              <div>
                <label
                  htmlFor="edit-title"
                  className="block text-sm font-medium text-gray-300 mb-2"
                >
                  Title
                </label>
                <input
                  id="edit-title"
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="w-full bg-white/5 border border-white/20 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Enter video title"
                  maxLength={100}
                />
                <p className="text-xs text-gray-500 mt-1">
                  {editTitle.length}/100 characters
                </p>
              </div>

              {/* Description */}
              <div>
                <label
                  htmlFor="edit-description"
                  className="block text-sm font-medium text-gray-300 mb-2"
                >
                  Description
                </label>
                <textarea
                  id="edit-description"
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  rows={6}
                  className="w-full bg-white/5 border border-white/20 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                  placeholder="Enter video description"
                  maxLength={5000}
                />
                <p className="text-xs text-gray-500 mt-1">
                  {editDescription.length}/5000 characters
                </p>
              </div>

              {/* Tags */}
              <div>
                <label
                  htmlFor="edit-tags"
                  className="block text-sm font-medium text-gray-300 mb-2"
                >
                  Tags
                </label>
                <input
                  id="edit-tags"
                  type="text"
                  value={editTags}
                  onChange={(e) => setEditTags(e.target.value)}
                  className="w-full bg-white/5 border border-white/20 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="tag1, tag2, tag3"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Separate tags with commas
                </p>
              </div>

              {/* Target Audience */}
              <div>
                <label
                  htmlFor="target-audience"
                  className="block text-sm font-medium text-gray-300 mb-2"
                >
                  Target Audience
                </label>
                <input
                  id="target-audience"
                  type="text"
                  value={targetAudience}
                  onChange={(e) => setTargetAudience(e.target.value)}
                  className="w-full bg-white/5 border border-white/20 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g., Beginners, Tech Enthusiasts"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Who is this video for?
                </p>
              </div>

              {/* AI Hints Button */}
              <button
                type="button"
                onClick={handleGenerateHints}
                disabled={generatingHints}
                className="w-full px-6 py-3 bg-gradient-to-r from-purple-600 via-pink-600 to-red-600 hover:from-purple-700 hover:via-pink-700 hover:to-red-700 text-white font-medium rounded-xl flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg hover:shadow-purple-500/50"
              >
                {generatingHints ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    Generating AI Suggestions...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-5 h-5" />
                    Get AI Improvement Hints
                  </>
                )}
              </button>

              {/* AI Hints Display */}
              {aiHints && (
                <div className="space-y-4">
                  {/* Title Suggestions */}
                  {aiHints.titles && aiHints.titles.length > 0 && (
                    <div className="glass rounded-xl p-5 border border-purple-500/30 bg-gradient-to-br from-purple-500/10 to-pink-500/5">
                      <div className="flex items-center gap-2 mb-3">
                        <Sparkles className="w-4 h-4 text-purple-400" />
                        <h3 className="text-lg font-bold text-white">
                          Title Suggestions
                        </h3>
                      </div>
                      <div className="space-y-2">
                        {aiHints.titles.map((title) => (
                          <div
                            key={title.substring(0, 20)}
                            className="flex items-start gap-3 p-3 rounded-lg bg-white/5 hover:bg-white/10 transition-colors group"
                          >
                            <div className="flex-1">
                              <p className="text-sm text-gray-300 leading-relaxed">
                                {title}
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => {
                                setEditTitle(title);
                                toast.success("Title applied!");
                              }}
                              className="p-2 rounded-lg bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 transition-all flex-shrink-0"
                              title="Apply this title"
                            >
                              <Plus className="w-4 h-4" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Description Suggestions */}
                  {aiHints.descriptions && aiHints.descriptions.length > 0 && (
                    <div className="glass rounded-xl p-5 border border-cyan-500/30 bg-gradient-to-br from-cyan-500/10 to-blue-500/5">
                      <div className="flex items-center gap-2 mb-3">
                        <Sparkles className="w-4 h-4 text-cyan-400" />
                        <h3 className="text-lg font-bold text-white">
                          Description Suggestions
                        </h3>
                      </div>
                      <div className="space-y-2">
                        {aiHints.descriptions.map((desc) => (
                          <div
                            key={desc.substring(0, 20)}
                            className="flex items-start gap-3 p-3 rounded-lg bg-white/5 hover:bg-white/10 transition-colors group"
                          >
                            <div className="flex-1">
                              <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
                                {desc}
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => {
                                setEditDescription(desc);
                                toast.success("Description applied!");
                              }}
                              className="p-2 rounded-lg bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 transition-all flex-shrink-0"
                              title="Apply this description"
                            >
                              <Plus className="w-4 h-4" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Tags Suggestions */}
                  {aiHints.tags && aiHints.tags.length > 0 && (
                    <div className="glass rounded-xl p-5 border border-pink-500/30 bg-gradient-to-br from-pink-500/10 to-red-500/5">
                      <div className="flex items-center gap-2 mb-3">
                        <Sparkles className="w-4 h-4 text-pink-400" />
                        <h3 className="text-lg font-bold text-white">
                          Tags Suggestions
                        </h3>
                      </div>
                      <div className="space-y-2">
                        {aiHints.tags.map((tagSet) => (
                          <div
                            key={tagSet.substring(0, 20)}
                            className="flex items-start gap-3 p-3 rounded-lg bg-white/5 hover:bg-white/10 transition-colors group"
                          >
                            <div className="flex-1">
                              <p className="text-sm text-gray-300 leading-relaxed">
                                {tagSet}
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => {
                                setEditTags(tagSet);
                                toast.success("Tags applied!");
                              }}
                              className="p-2 rounded-lg bg-pink-500/20 hover:bg-pink-500/30 text-pink-300 transition-all flex-shrink-0"
                              title="Apply these tags"
                            >
                              <Plus className="w-4 h-4" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* General Tips */}
                  {aiHints.general && (
                    <div className="glass rounded-xl p-5 border border-green-500/30 bg-gradient-to-br from-green-500/10 to-emerald-500/5">
                      <div className="flex items-center gap-2 mb-3">
                        <Sparkles className="w-4 h-4 text-green-400" />
                        <h3 className="text-lg font-bold text-white">
                          General Tips
                        </h3>
                      </div>
                      <p className="text-sm text-gray-300 leading-relaxed">
                        {aiHints.general}
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* Video Stats */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 p-4 glass rounded-xl border border-white/10">
                <div className="text-center">
                  <div className="text-lg font-bold text-white">
                    {editingVideo.statistics?.viewCount
                      ? parseInt(
                          editingVideo.statistics.viewCount,
                          10,
                        ).toLocaleString()
                      : "0"}
                  </div>
                  <div className="text-xs text-gray-400">Views</div>
                </div>
                <div className="text-center">
                  <div className="text-lg font-bold text-white">
                    {editingVideo.statistics?.likeCount
                      ? parseInt(
                          editingVideo.statistics.likeCount,
                          10,
                        ).toLocaleString()
                      : "0"}
                  </div>
                  <div className="text-xs text-gray-400">Likes</div>
                </div>
                <div className="text-center">
                  <div className="text-lg font-bold text-white">
                    {editingVideo.statistics?.commentCount
                      ? parseInt(
                          editingVideo.statistics.commentCount,
                          10,
                        ).toLocaleString()
                      : "0"}
                  </div>
                  <div className="text-xs text-gray-400">Comments</div>
                </div>
                <div className="text-center">
                  <div className="text-sm font-bold text-white">
                    {new Date(
                      editingVideo.snippet?.publishedAt,
                    ).toLocaleDateString()}
                  </div>
                  <div className="text-xs text-gray-400">Published</div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-3 pt-4 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setEditingVideo(null)}
                  disabled={saving}
                  className="flex-1 px-6 py-3 bg-white/5 hover:bg-white/10 text-white font-medium rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSaveMetadata}
                  disabled={saving || !editTitle}
                  className="flex-1 px-6 py-3 bg-gradient-to-r from-purple-600 via-pink-600 to-red-600 hover:from-purple-700 hover:via-pink-700 hover:to-red-700 text-white font-medium rounded-xl transition-all shadow-lg hover:shadow-purple-500/50 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  {saving ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    "Save Changes"
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </UIWrapper>
  );
};

export default DashboardPage;
