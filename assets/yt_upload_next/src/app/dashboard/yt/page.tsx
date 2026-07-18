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
  LogOut,
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
  const [userId, setUserId] = useState("");
  const [channelData, setChannelData] = useState<any>(null);
  const [analytics, setAnalytics] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ message: string; code?: number } | null>(
    null,
  );

  // Upload State
  const [uploading, setUploading] = useState(false);
  const [improving, setImproving] = useState(false);
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
    const uid =
      localStorage.getItem("user_id") ||
      document.cookie.match(/user_id=([^;]+)/)?.[1];
    if (!token || !uid) {
      router.push("/sign-in");
      return;
    }
    setAccessToken(token);
    setUserId(uid);
  }, [router]);

  const fetchChannelData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/google", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "getChannelData",
          accessToken,
          userId,
        }),
      });
      const result = await response.json();

      if (result.success) {
        setChannelData(result);
      } else {
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
  }, [accessToken, userId]);

  const fetchAnalytics = useCallback(async () => {
    try {
      const response = await fetch("/api/google", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "getAnalytics", accessToken, userId }),
      });
      const result = await response.json();
      if (result.success) {
        setAnalytics(result);
      }
    } catch (error) {
      console.error("Analytics fetch error:", error);
    }
  }, [accessToken, userId]);

  useEffect(() => {
    if (accessToken) {
      fetchChannelData();
      fetchAnalytics();
    }
  }, [accessToken, fetchChannelData, fetchAnalytics]);

  const handleImproveWithAI = async () => {
    if (!title.trim()) {
      toast.error("Please enter a title first.");
      return;
    }
    setImproving(true);
    const toastId = toast.loading("Generating SEO suggestions...");
    try {
      const response = await fetch("/api/groq", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description, tags }),
      });
      const result = await response.json();
      if (result.success) {
        setTitle(result.title || title);
        setDescription(result.description || description);
        setTags(result.tags || tags);
        toast.success("SEO suggestions applied! Review before uploading.", {
          id: toastId,
        });
      } else {
        toast.error(result.error || "Failed to generate suggestions", {
          id: toastId,
        });
      }
    } catch (error: any) {
      toast.error(`Error: ${error.message}`, { id: toastId });
    } finally {
      setImproving(false);
    }
  };

  const handleUpload = async () => {
    if (!videoFile) {
      toast.error("Please select a video file to upload.");
      return;
    }
    if (!title.trim()) {
      toast.error("Please enter a video title.");
      return;
    }
    setUploading(true);
    const toastId = toast.loading("Uploading video to YouTube...");
    try {
      const formData = new FormData();
      formData.append("action", "uploadVideo");
      formData.append("videoFile", videoFile);
      formData.append("title", title);
      formData.append("description", description);
      formData.append("tags", tags);
      formData.append("privacy", privacy);
      formData.append("accessToken", accessToken);
      formData.append("userId", userId);

      const response = await fetch("/api/google", {
        method: "POST",
        body: formData,
      });
      const result = await response.json();

      if (result.success) {
        toast.success("Video uploaded successfully!", { id: toastId });
        setVideoFile(null);
        setTitle("");
        setDescription("");
        setTags("");
        setPrivacy("private");
        fetchChannelData();
        fetchAnalytics();
      } else {
        toast.error(`Upload failed: ${result.error}`, { id: toastId });
      }
    } catch (error: any) {
      toast.error(`Upload error: ${error.message}`, { id: toastId });
    } finally {
      setUploading(false);
    }
  };

  const handleEditClick = (video: any) => {
    const videoId = video.snippet?.resourceId?.videoId || video.id;
    setEditingVideo({ ...video, id: videoId });
    setEditTitle(video.snippet?.title || "");
    setEditDescription(video.snippet?.description || "");
    setEditTags(video.snippet?.tags?.join(", ") || "");
    setAiHints(null);
  };

  const handleSaveMetadata = async () => {
    if (!editingVideo) return;
    setSaving(true);
    const toastId = toast.loading("Saving metadata...");
    try {
      const response = await fetch("/api/google", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "updateVideo",
          accessToken,
          userId,
          videoId: editingVideo.id,
          title: editTitle,
          description: editDescription,
          tags: editTags,
        }),
      });
      const result = await response.json();
      if (result.success) {
        toast.success("Metadata updated!", { id: toastId });
        setEditingVideo(null);
        fetchChannelData();
      } else {
        toast.error(`Update failed: ${result.error}`, { id: toastId });
      }
    } catch (error: any) {
      toast.error(`Update error: ${error.message}`, { id: toastId });
    } finally {
      setSaving(false);
    }
  };

  const handleGenerateHints = async () => {
    setGeneratingHints(true);
    const toastId = toast.loading("Generating AI hints...");
    try {
      const response = await fetch("/api/groq", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "generateMetadata",
          title: editTitle,
          description: editDescription,
          tags: editTags,
          targetAudience,
        }),
      });
      const result = await response.json();
      if (result.success) {
        setAiHints(result.hints);
        toast.success("Hints generated!", { id: toastId });
      } else {
        toast.error(`Failed to generate hints: ${result.error}`, {
          id: toastId,
        });
      }
    } catch (error: any) {
      toast.error(`Generation error: ${error.message}`, { id: toastId });
    } finally {
      setGeneratingHints(false);
    }
  };

  const applySuggestion = (
    field: "title" | "description" | "tags",
    value: string,
  ) => {
    if (field === "title") setEditTitle(value);
    else if (field === "description") setEditDescription(value);
    else if (field === "tags") {
      const current = editTags
        .split(",")
        .map((t) => t.trim().toLowerCase())
        .filter(Boolean);
      const existing = new Set(current);
      const newTags = value
        .split(",")
        .map((t) => t.trim())
        .filter((t) => t && !existing.has(t.toLowerCase()));
      setEditTags([...current, ...newTags].join(", "));
    }
  };

  const remainingChars = (text: string, max: number) => max - text.length;

  // --- Loading Skeleton ---
  if (loading && !channelData) {
    return (
      <UIWrapper>
        <div className="flex-1 max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                className="rounded-[18px] bg-white/5 p-6 animate-pulse"
              >
                <div className="h-4 bg-[#e0e0e0] rounded w-1/2 mb-3" />
                <div className="h-8 bg-[#e0e0e0] rounded w-1/3" />
              </div>
            ))}
          </div>
          <div className="rounded-[18px] bg-white/5 p-6 animate-pulse">
            <div className="h-4 bg-[#e0e0e0] rounded w-1/4 mb-4" />
            <div className="h-12 bg-[#e0e0e0] rounded w-full" />
          </div>
        </div>
      </UIWrapper>
    );
  }

  // --- Error State ---
  if (error) {
    return (
      <UIWrapper>
        <div className="flex-1 max-w-7xl mx-auto px-4 sm:px-6 py-12 flex items-center justify-center">
          <div className="max-w-md w-full text-center">
            <div className="w-16 h-16 rounded-full bg-[#0066cc]/10 flex items-center justify-center mx-auto mb-6">
              <AlertCircle className="w-8 h-8 text-[#0066cc]" />
            </div>
            <h2 className="text-[22px] font-semibold text-white mb-2">
              {error.code === 401
                ? "Authentication Required"
                : "Error Loading Data"}
            </h2>
            <p className="text-[15px] text-white/50 mb-8">
              {error.code === 401
                ? "Your YouTube connection has expired. Please reconnect to continue."
                : error.message}
            </p>
            {error.code === 401 ? (
              <a
                href="/sign-in"
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#0066cc]/85 backdrop-blur-xl text-white text-[15px] rounded-full hover:bg-[#0066cc] transition-colors active:scale-[0.95] border-[0.5px] border-white/20"
              >
                <LogOut className="w-5 h-5" />
                Sign Out
              </a>
            ) : (
              <button
                onClick={() => {
                  setError(null);
                  fetchChannelData();
                }}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-white/5 backdrop-blur-xl text-white text-[15px] rounded-full hover:bg-white/10 transition-colors active:scale-[0.95] border-[0.5px] border-white/10"
              >
                Sign Out
              </button>
            )}
          </div>
        </div>
      </UIWrapper>
    );
  }

  // --- Main Content ---
  const stats = channelData?.statistics || {};
  const videos = channelData?.videos || [];

  return (
    <UIWrapper>
      <div className="flex-1 max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* Channel Overview Stats */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
          {/* Subscribers */}
          <div className="bg-white/5 backdrop-blur-2xl rounded-[18px] p-6 border border-white/10 shadow-[0_1px_3px_rgba(0,0,0,0.2)]">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-[#0066cc]/10 flex items-center justify-center">
                <Users className="w-5 h-5 text-[#0066cc]" />
              </div>
              <span className="text-[14px] text-white/50">Subscribers</span>
            </div>
            <div className="text-[32px] font-semibold text-white tracking-tight">
              {stats.subscriberCount || "—"}
            </div>
          </div>

          {/* Total Views */}
          <div className="bg-white/5 backdrop-blur-2xl rounded-[18px] p-6 border border-white/10 shadow-[0_1px_3px_rgba(0,0,0,0.2)]">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-[#0066cc]/10 flex items-center justify-center">
                <Eye className="w-5 h-5 text-[#0066cc]" />
              </div>
              <span className="text-[14px] text-white/50">Total Views</span>
            </div>
            <div className="text-[32px] font-semibold text-white tracking-tight">
              {stats.viewCount || "—"}
            </div>
          </div>

          {/* Videos */}
          <div className="bg-white/5 backdrop-blur-2xl rounded-[18px] p-6 border border-white/10 shadow-[0_1px_3px_rgba(0,0,0,0.2)]">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-[#0066cc]/10 flex items-center justify-center">
                <BarChart3 className="w-5 h-5 text-[#0066cc]" />
              </div>
              <span className="text-[14px] text-white/50">Videos</span>
            </div>
            <div className="text-[32px] font-semibold text-white tracking-tight">
              {stats.videoCount || "—"}
            </div>
          </div>
        </div>

        {/* Upload Section */}
        <div className="bg-white/5 backdrop-blur-2xl rounded-[18px] p-8 border border-white/10 shadow-[0_1px_3px_rgba(0,0,0,0.2)]">
          <h2 className="text-[20px] font-semibold text-white mb-6">
            Upload Video
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            {/* Left: File picker */}
            <div className="space-y-4">
              <label className="flex flex-col items-center justify-center h-48 rounded-[18px] border-2 border-dashed border-[#e0e0e0] bg-white/50 cursor-pointer hover:border-[#0066cc]/40 transition-colors">
                <Upload className="w-8 h-8 text-white/50 mb-2" />
                <span className="text-[14px] text-white/50">
                  {videoFile ? videoFile.name : "Click to select a video file"}
                </span>
                <input
                  type="file"
                  accept="video/*"
                  className="hidden"
                  onChange={(e) => setVideoFile(e.target.files?.[0] || null)}
                />
              </label>
              <div>
                <label className="text-[13px] text-white/50 mb-1 block">
                  Privacy
                </label>
                <select
                  value={privacy}
                  onChange={(e) => setPrivacy(e.target.value)}
                  className="w-full rounded-full bg-white/5 backdrop-blur-xl border border-white/10 px-4 py-2.5 text-[14px] text-white focus:outline-none focus:ring-2 focus:ring-[#0066cc]/30"
                >
                  <option value="private">Private</option>
                  <option value="unlisted">Unlisted</option>
                  <option value="public">Public</option>
                </select>
              </div>
            </div>

            {/* Right: Metadata inputs */}
            <div className="space-y-4">
              <input
                type="text"
                placeholder="Video title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full rounded-full bg-white/5 backdrop-blur-xl border border-white/10 px-5 py-2.5 text-[14px] text-white placeholder:text-white/50 focus:outline-none focus:ring-2 focus:ring-[#0066cc]/30"
              />
              <textarea
                placeholder="Video description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                className="w-full rounded-[18px] bg-white/5 backdrop-blur-xl border border-white/10 px-5 py-2.5 text-[14px] text-white placeholder:text-white/50 focus:outline-none focus:ring-2 focus:ring-[#0066cc]/30 resize-none"
              />
              <input
                type="text"
                placeholder="Tags (comma separated)"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                className="w-full rounded-full bg-white/5 backdrop-blur-xl border border-white/10 px-5 py-2.5 text-[14px] text-white placeholder:text-white/50 focus:outline-none focus:ring-2 focus:ring-[#0066cc]/30"
              />
              <button
                onClick={handleImproveWithAI}
                disabled={improving || !title.trim()}
                className="w-full inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-white/5 backdrop-blur-xl border border-[#0066cc]/30 text-[#0066cc] text-[14px] rounded-full hover:bg-[#0066cc]/10 transition-colors active:scale-[0.95] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {improving ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <Sparkles className="w-5 h-5" />
                )}
                {improving ? "Generating..." : "Improve with AI"}
              </button>
              <button
                onClick={handleUpload}
                disabled={uploading || !videoFile}
                className="w-full inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-[#0066cc]/85 backdrop-blur-xl text-white text-[15px] rounded-full hover:bg-[#0066cc] transition-colors active:scale-[0.95] border-[0.5px] border-white/20 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {uploading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <Upload className="w-5 h-5" />
                )}
                {uploading ? "Uploading..." : "Upload to YouTube"}
              </button>
            </div>
          </div>
        </div>

        {/* 30-Day Analytics */}
        {analytics?.analytics && (
          <div className="bg-white/5 backdrop-blur-2xl rounded-[18px] p-8 border border-white/10 shadow-[0_1px_3px_rgba(0,0,0,0.2)]">
            <h2 className="text-[20px] font-semibold text-white mb-6">
              30-Day Analytics
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
              <div>
                <div className="text-[24px] font-semibold text-white">
                  {analytics.analytics.views?.toLocaleString() || "—"}
                </div>
                <div className="text-[13px] text-white/50">Views</div>
              </div>
              <div>
                <div className="text-[24px] font-semibold text-white">
                  {Math.round(
                    analytics.analytics.watchTime / 60,
                  )?.toLocaleString() || "—"}{" "}
                  min
                </div>
                <div className="text-[13px] text-white/50">Watch Time</div>
              </div>
              <div>
                <div className="text-[24px] font-semibold text-white">
                  {analytics.analytics.likes?.toLocaleString() || "—"}
                </div>
                <div className="text-[13px] text-white/50">Likes</div>
              </div>
              <div>
                <div className="text-[24px] font-semibold text-white">
                  {analytics.analytics.subscribersGained?.toLocaleString() ||
                    "—"}
                </div>
                <div className="text-[13px] text-white/50">Subscribers</div>
              </div>
            </div>
          </div>
        )}

        {/* All Videos */}
        {videos.length > 0 && (
          <div className="bg-white/5 backdrop-blur-2xl rounded-[18px] p-8 border border-white/10 shadow-[0_1px_3px_rgba(0,0,0,0.2)]">
            <h2 className="text-[20px] font-semibold text-white mb-6">
              All Videos ({videos.length})
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {videos.map((video: any) => (
                <div
                  key={video.id}
                  className="bg-white/5 backdrop-blur-xl rounded-[18px] border border-white/10 overflow-hidden hover:border-[#0066cc]/30 transition-colors group"
                >
                  {/* Thumbnail */}
                  <div className="relative aspect-video bg-white/10 overflow-hidden">
                    {video.snippet?.thumbnails?.medium?.url && (
                      <img
                        src={video.snippet.thumbnails.medium.url}
                        alt={video.snippet.title}
                        className="w-full h-full object-cover"
                      />
                    )}
                    <a
                      href={`https://youtube.com/watch?v=${video.id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="absolute inset-0 flex items-center justify-center bg-black/0 hover:bg-black/20 transition-colors opacity-0 group-hover:opacity-100"
                    >
                      <div className="w-12 h-12 rounded-full bg-[#0066cc]/85 backdrop-blur-xl flex items-center justify-center">
                        <Eye className="w-5 h-5 text-white" />
                      </div>
                    </a>
                  </div>

                  {/* Info */}
                  <div className="p-4 space-y-2">
                    <h3 className="text-[13px] font-medium text-white line-clamp-2">
                      {video.snippet?.title || "Untitled"}
                    </h3>
                    <div className="flex items-center justify-between text-[11px] text-white/50">
                      <span>{video.statistics?.viewCount || 0} views</span>
                      <span>
                        {video.snippet?.publishedAt
                          ? new Date(
                              video.snippet.publishedAt,
                            ).toLocaleDateString()
                          : ""}
                      </span>
                    </div>
                    <div className="flex items-center justify-between pt-2 border-t border-[#e0e0e0]/40">
                      <span className="text-[11px] text-white/50 capitalize">
                        {video.status?.privacyStatus || "private"}
                      </span>
                      <button
                        onClick={() => handleEditClick(video)}
                        className="flex items-center gap-1 text-[11px] text-[#0066cc] hover:underline"
                      >
                        <Edit2 className="w-3 h-3" />
                        Edit
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Edit Metadata Dialog */}
      {editingVideo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-2xl max-h-[90vh] flex flex-col bg-white/5 backdrop-blur-2xl rounded-[18px] border border-white/20 shadow-[0_8px_32px_rgba(0,0,0,0.12)]">
            {/* Sticky header */}
            <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 border-b border-white/10 bg-black/80 backdrop-blur-xl rounded-t-[18px]">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-full bg-[#0066cc]/10 flex items-center justify-center">
                  <Edit2 className="w-4 h-4 text-[#0066cc]" />
                </div>
                <span className="text-[15px] font-semibold text-white">
                  Edit Metadata
                </span>
              </div>
              <button
                onClick={() => setEditingVideo(null)}
                className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center hover:bg-[#e0e0e0]/60 transition-colors"
              >
                <X className="w-4 h-4 text-white/50" />
              </button>
            </div>

            {/* Scrollable body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-5">
              {/* Thumbnail */}
              {editingVideo.snippet?.thumbnails?.medium?.url && (
                <img
                  src={editingVideo.snippet.thumbnails.medium.url}
                  alt="Thumbnail"
                  className="w-full rounded-[12px] border border-white/10"
                />
              )}

              {/* Title */}
              <div>
                <label className="text-[13px] text-white/50 mb-1 block">
                  Title
                </label>
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  maxLength={100}
                  className="w-full rounded-full bg-white/5 backdrop-blur-xl border border-white/10 px-5 py-2.5 text-[14px] text-white focus:outline-none focus:ring-2 focus:ring-[#0066cc]/30"
                />
                <div className="text-[11px] text-white/50 mt-1 text-right">
                  {remainingChars(editTitle, 100)} / 100
                </div>
              </div>

              {/* Description */}
              <div>
                <label className="text-[13px] text-white/50 mb-1 block">
                  Description
                </label>
                <textarea
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  maxLength={5000}
                  rows={4}
                  className="w-full rounded-[18px] bg-white/5 backdrop-blur-xl border border-white/10 px-5 py-2.5 text-[14px] text-white focus:outline-none focus:ring-2 focus:ring-[#0066cc]/30 resize-none"
                />
                <div className="text-[11px] text-white/50 mt-1 text-right">
                  {remainingChars(editDescription, 5000)} / 5000
                </div>
              </div>

              {/* Tags */}
              <div>
                <label className="text-[13px] text-white/50 mb-1 block">
                  Tags
                </label>
                <input
                  type="text"
                  value={editTags}
                  onChange={(e) => setEditTags(e.target.value)}
                  placeholder="Comma separated"
                  className="w-full rounded-full bg-white/5 backdrop-blur-xl border border-white/10 px-5 py-2.5 text-[14px] text-white placeholder:text-white/50 focus:outline-none focus:ring-2 focus:ring-[#0066cc]/30"
                />
              </div>

              {/* Target Audience */}
              <div>
                <label className="text-[13px] text-white/50 mb-1 block">
                  Target Audience
                </label>
                <input
                  type="text"
                  value={targetAudience}
                  onChange={(e) => setTargetAudience(e.target.value)}
                  className="w-full rounded-full bg-white/5 backdrop-blur-xl border border-white/10 px-5 py-2.5 text-[14px] text-white focus:outline-none focus:ring-2 focus:ring-[#0066cc]/30"
                />
              </div>

              {/* AI Hints Button */}
              <button
                onClick={handleGenerateHints}
                disabled={generatingHints}
                className="w-full inline-flex items-center justify-center gap-2 px-5 py-2.5 bg-[#0066cc]/85 backdrop-blur-xl text-white text-[14px] rounded-full hover:bg-[#0066cc] transition-colors active:scale-[0.95] border-[0.5px] border-white/20 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {generatingHints ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Sparkles className="w-4 h-4" />
                )}
                {generatingHints ? "Generating..." : "Get AI Improvement Hints"}
              </button>

              {/* AI Hints Display */}
              {aiHints && (
                <div className="space-y-4">
                  {aiHints.titles?.length > 0 && (
                    <div className="bg-white/5 backdrop-blur-xl rounded-[18px] p-5 border border-white/10">
                      <div className="flex items-center gap-2 mb-3">
                        <Sparkles className="w-4 h-4 text-[#0066cc]" />
                        <h4 className="text-[14px] font-semibold text-white">
                          Title Suggestions
                        </h4>
                      </div>
                      <div className="space-y-2">
                        {aiHints.titles.map((hint, i) => (
                          <div
                            key={i}
                            className="flex items-center gap-2 text-[13px] text-white/50"
                          >
                            <span className="flex-1">{hint}</span>
                            <button
                              onClick={() => applySuggestion("title", hint)}
                              className="w-6 h-6 rounded-full bg-[#0066cc]/10 flex items-center justify-center hover:bg-[#0066cc]/20 transition-colors"
                            >
                              <Plus className="w-3 h-3 text-[#0066cc]" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {aiHints.descriptions?.length > 0 && (
                    <div className="bg-white/5 backdrop-blur-xl rounded-[18px] p-5 border border-white/10">
                      <div className="flex items-center gap-2 mb-3">
                        <Sparkles className="w-4 h-4 text-[#0066cc]" />
                        <h4 className="text-[14px] font-semibold text-white">
                          Description Suggestions
                        </h4>
                      </div>
                      <div className="space-y-2">
                        {aiHints.descriptions.map((hint, i) => (
                          <div
                            key={i}
                            className="flex items-center gap-2 text-[13px] text-white/50"
                          >
                            <span className="flex-1">{hint}</span>
                            <button
                              onClick={() =>
                                applySuggestion("description", hint)
                              }
                              className="w-6 h-6 rounded-full bg-[#0066cc]/10 flex items-center justify-center hover:bg-[#0066cc]/20 transition-colors"
                            >
                              <Plus className="w-3 h-3 text-[#0066cc]" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {aiHints.tags?.length > 0 && (
                    <div className="bg-white/5 backdrop-blur-xl rounded-[18px] p-5 border border-white/10">
                      <div className="flex items-center gap-2 mb-3">
                        <Sparkles className="w-4 h-4 text-[#0066cc]" />
                        <h4 className="text-[14px] font-semibold text-white">
                          Tags Suggestions
                        </h4>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {aiHints.tags.map((hint, i) => (
                          <button
                            key={i}
                            onClick={() => applySuggestion("tags", hint)}
                            className="text-[12px] px-3 py-1 rounded-full bg-black/30 backdrop-blur-xl border border-[#0066cc]/30 text-[#0066cc] hover:bg-[#0066cc]/10 transition-colors"
                          >
                            + {hint}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {aiHints.general && (
                    <div className="bg-white/5 backdrop-blur-xl rounded-[18px] p-5 border border-white/10">
                      <div className="flex items-center gap-2 mb-3">
                        <Sparkles className="w-4 h-4 text-[#0066cc]" />
                        <h4 className="text-[14px] font-semibold text-white">
                          General Tips
                        </h4>
                      </div>
                      <p className="text-[13px] text-white/50">
                        {aiHints.general}
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* Video Stats */}
              {editingVideo.statistics && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 bg-white/5 backdrop-blur-xl rounded-[18px] p-5 border border-white/10">
                  <div>
                    <div className="text-[18px] font-semibold text-white">
                      {editingVideo.statistics.viewCount || 0}
                    </div>
                    <div className="text-[11px] text-white/50">Views</div>
                  </div>
                  <div>
                    <div className="text-[18px] font-semibold text-white">
                      {editingVideo.statistics.likeCount || 0}
                    </div>
                    <div className="text-[11px] text-white/50">Likes</div>
                  </div>
                  <div>
                    <div className="text-[18px] font-semibold text-white">
                      {editingVideo.statistics.commentCount || 0}
                    </div>
                    <div className="text-[11px] text-white/50">Comments</div>
                  </div>
                  <div>
                    <div className="text-[18px] font-semibold text-white">
                      {editingVideo.snippet?.publishedAt
                        ? new Date(
                            editingVideo.snippet.publishedAt,
                          ).toLocaleDateString()
                        : "—"}
                    </div>
                    <div className="text-[11px] text-white/50">Published</div>
                  </div>
                </div>
              )}

              {/* Action buttons */}
              <div className="flex items-center justify-end gap-3 pt-4 border-t border-[#e0e0e0]/60">
                <button
                  onClick={() => setEditingVideo(null)}
                  className="px-5 py-2.5 text-[14px] text-white/50 rounded-full hover:bg-white/10 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveMetadata}
                  disabled={saving}
                  className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#0066cc]/85 backdrop-blur-xl text-white text-[14px] rounded-full hover:bg-[#0066cc] transition-colors active:scale-[0.95] border-[0.5px] border-white/20 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {saving ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Sparkles className="w-4 h-4" />
                  )}
                  {saving ? "Saving..." : "Save Changes"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </UIWrapper>
  );
};

export default function Page() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center bg-black">
          <div className="w-8 h-8 border-2 border-[#0066cc] border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <DashboardPage />
    </Suspense>
  );
}
